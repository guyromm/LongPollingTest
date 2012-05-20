# -*- coding: utf-8 -*-
'''
filedesc: default controller file
'''
from noodles.http import Response,XResponse
import json
import gevent

def index(request):
    return Response('<h1>Hello, NoodlesFramework!</h1>')

import datetime,time
from gevent import Greenlet,queue
import weakref
import hashlib
#decorators
from longpolling import action,greenlet
#classes
from longpolling import GreenletMixin,LPVirtSocket,LPHandler


#**** demonstration of long polling ****

class IncrementorController(LPHandler):
    "Example incrementor handler class."
    stopped=False
    @greenlet
    def increment(self):
        while not self.stopped:
            self.cnt+=1
            gevent.sleep(0.2)
            self.send({'number':self.cnt})
    @action
    def putaction(self,pkg,request=None):
        #assert pkg['client_token']==self.sockref().utok,"tokens do not match %s , %s, %s, %s"%(pkg,self.sockref().utok,self.chan,self.utok)
        self.send({'content':pkg,'channel_ident':self.sockref().utok})
        return XResponse({'result':'ok'})
    @action
    def stop(self,pkg,request):
        self.stopped=True
        self.kill_greenlets('incrementor')
        return XResponse({'result':'ok','value':self.stopped})
    def __init__(self,chan,sock,utok):
        #test specific
        LPHandler.__init__(self,chan,sock,utok)
        self.cnt=0
        self.startincrementor()
    @action
    def startincrementor(self,pkg=None,request=None):
        self.stopped=False
        self.increment()
        if request: return XResponse({'result':'ok','value':self.stopped})
    def onmessage(self,pkg,request=None):
        print('just received %s via %s'%(pkg,self.sockref().utok))

class DecrementorController(LPHandler):
    cnt=10
    @greenlet
    def decrement(self):
        while self.cnt:
            self.cnt-=1
            gevent.sleep(0.5)
            self.send({'number':self.cnt})
    def __init__(self,chan,sock,utok):
        LPHandler.__init__(self,chan,sock,utok)
        self.decrement()

class TestSock(LPVirtSocket):
    
    channels={'incrementor':IncrementorController
              ,'decrementor':DecrementorController
              }
    enabled_onstart=['incrementor','decrementor']
    pass




#**** this is a demonstration of streaming ****
from noodles.websocket.streaming import StreamQueue ,PartialResponse
def streamer(request,conn_id):
    resp = PartialResponse()
    resp.content_type='text/plain'
    body = StreamQueue(resp)
    body.put(' '*1000)
    body.put('current time:\n')

    g = Greenlet.spawn(current_time,body)

    return body

def current_time(body):
    current = start = datetime.datetime.now()
    end = start + datetime.timedelta(seconds=60)

    while current < end:
        current = datetime.datetime.now()
        body.put('%s\n' % current.strftime("%Y-%m-%d %I:%M:%S"))
        gevent.sleep(1)

    body.put('all done\n')
    body.put(StopIteration)

