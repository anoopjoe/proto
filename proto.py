'''
The Proto! Python Async RPC based on Protobufers and TCP sokets.
Licenced under LPGLv2+.
Created on  Oct 24, 2009

@author: Stanislav Yudin
'''
from google.protobuf.service import RpcChannel, RpcController
import sys
import logging
import time
import socket
import threading
import SocketServer
import simplejson

log = logging.getLogger(__name__)
MAX_PACKET = 16000

__pb2_module = None

def get_pb2_module():
	global __pb2_module
	return __pb2_module

def set_pb2_module(module):
	global __pb2_module
	if not __pb2_module:
		__pb2_module = module

__impl_module = None
def get_impl_module():
	global __impl_module
	return __impl_module

def set_impl_module(module):
	global __impl_module
	if not __impl_module:
		__impl_module = module

class ProtoError(Exception):
	pass

class ProtoController(RpcController):
	error = None

	def Reset(self):
		"""
		Resets the RpcController to its initial state. 	source code
		"""
		self.error = None
  	
	def Failed(self):
		"""
		Returns true if the call failed. 	source code
		"""
		return self.error
  	
	def ErrorText(self):
		"""
		If Failed is true, returns a human-readable description of the error. 	source code
		"""
	 	return self.error
  	
	def StartCancel(self):
		"""
		Initiate cancellation. 	source code
		"""
		pass

	def SetFailed(self, reason):
		"""
		Sets a failure reason. 	source code
	  	"""
	  	self.error = reason
  	
  	def IsCanceled(self):
	  	"""
	  	Checks if the client cancelled the RPC. 	source code
	  	"""
	  	return false
	  	
  	def NotifyOnCancel(self, callback):
  		log.error('notify: %s' % callback)
  		pass

class ThreadedTCPRequestHandler(SocketServer.BaseRequestHandler):	
	def handle(self):
		data = self.request.recv(MAX_PACKET)
		log.debug('received raw data (%s): %s' % (len(data), data))
		if not data:
			log.error('No data!')
			return
			
		service_name, method_name, request_inst, response_class = decode(data)
		self.CallMethod(service_name, method_name, request_inst, response_class)
		self.request.send(data)
		
	def callback(self, object):
		log.info('callback: %s', object)
	        
	def CallMethod(self, service_name, method_name, request_inst, response_class):
		"""
			Call server implementation of service_name->method_name
			returns response_class instance
		"""
		log.info(' +started+ API calling %s->%s' % (service_name, method_name) )
		done = None
		c = ProtoController()
		#creating implementation of requested server
		service = getattr(get_impl_module(), service_name + 'Impl')()
		log.debug('Service object: %s' % service)
		method = service.GetDescriptor().FindMethodByName(method_name)
		if not method:
			log.fatal('Failed to find method %s' % method_name)
			raise ProtoError('Failed to find method %s' % method_name)
		log.debug('Method object: %s - %s' % ( method.name, method ))
		log.debug('Request object: %s' % (type(request_inst)))
		log.debug('Response class: %s' % response_class)
		res = service.CallMethod(method, c, request_inst, self.callback)
		if c.Failed():
			self.request.send(simplejson.dumps({'error':  c.error }))
			log.fatal('+error+ API failed %s->%s : %s' % (service_name, method_name, c.error) )
		else:
			answer = encode(service_name + 'Impl',
							method_name,
							res, #answer instead or request
							response_class)
			self.request.send(answer)
			log.info(' +finished+ API called %s->%s = %s' % (service_name, method_name, answer))
		
class ThreadedTCPServer(SocketServer.ThreadingMixIn, SocketServer.TCPServer):
    pass
   
def encode(service_name, method_name, request, response_class):
	packet = {}
	packet['service'] = service_name
	packet['method'] = method_name
	packet['request_class'] = type(request).__name__
	packet['request'] = request.SerializeToString()
	packet['response_class'] = response_class.__name__
	p = simplejson.dumps(packet)
	log.debug('encoded packet: %s' % p)
	return p

def decode(data):
	packet = simplejson.loads(data)
	if not isinstance(packet, dict):
		raise ProtoError('Invalid data for decoding')
	log.debug('decoded packet (size=%s): %s' % (len(data), packet))
	service_name = packet['service']
	method_name = packet['method']
	request_class = getattr(get_pb2_module(),str(packet['request_class']))
	request_inst = request_class()
	request_inst.ParseFromString(packet['request'])
	response_class = getattr(get_pb2_module(), str(packet['response_class']))
	return service_name, method_name, request_inst, response_class

def send_receive(sock, packet):
	log.debug('sending...')
	sock.send(packet)
	log.debug('receiving...')
	response = sock.recv(MAX_PACKET)
	if not response:
		log.error('No response!')
		sys.exit(-1)
	log.debug('gochaa!')
	return decode(response)
   
def run_server(port, pb2, impl):
	run_server_thread(port, pb2, impl)[1].join()
	
def run_server_thread(port, pb2, impl):
	set_pb2_module(pb2)
	set_impl_module(impl)
	
	log.info('Starting server for %s: %s' % ('localhost', port))
	server = ThreadedTCPServer(('localhost', port), ThreadedTCPRequestHandler)
	ip, port = server.server_address
    # Start a thread with the server -- that thread will then start one
    # more thread for each request
	server_thread = threading.Thread(target=server.serve_forever)
    # Exit the server thread when the main thread terminates
	server_thread.setDaemon(True)
	server_thread.start()
	#log.info("Server loop running in thread:", server_thread.getName())
	return server, server_thread

class ProtoChannel(RpcChannel):
	"""
		Client access 
	"""
	def __init__(self, host, port, pb2):
		set_pb2_module(pb2)
		self.host = host
		self.port = port
		self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		self.sock.connect((host, port))
		log.info('opening channel to %s:%s' % (host, port))
	
	def CallMethod(self, md, rpc_controller, request, response_class, done):
		"""
			Calls the method identified by the descriptor.

			Call the given method of the remote service. 
			The signature of this procedure looks the same as Service.CallMethod(), 
			but the requirements are less strict in one important way: the request 
			object doesn't have to be of any specific class as long as its 
			descriptor is method.input_type.
		"""
		log.debug('API proxy call: %s' % md.full_name)
		log.debug('Method object: %s - %s' % ( md.name, md ))
		log.debug('Request object: %s' % (type(request)))
		log.debug('Response class: %s' % response_class)
		
		packet = encode(md.containing_service.name, md.name, request, response_class )		
		answer = send_receive(self.sock, packet )
		
		log.debug('answer: (%s) %s' % (type(answer), answer))
		done(answer)
		log.debug('call finished')
		return answer