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



def action(f):
    def action_wrapper(*args,**kw):
        f.allowed=True
        return f(*args,**kw)

    return action_wrapper


class LongPollingHandler(object):
    MAX_POLL_IDLETIME=3
    #uninitialized queue
    _tosend = None

    def kill_greenlets(self,gn=None):
        #obtain the dict of greenlets we want to specifically kill
        gt = dict([(gk,gl) for gk,gl in self.greenlets.items()\
                       if ((gn and gk==gn) or True)])
        gtv = gt.values()
        gtk = gt.keys()
        print 'beginning to kill %s greenlets'%(len(gtk))
        #do the killing
        gevent.killall(gtv,block=False)
        #del the dict references
        for gtkey in gtk: del self.greenlets[gtkey]
    def _kill(self):
        global connections
        self.kill_greenlets()
        try:
            del connections[self.utok]
        except KeyError:
            print 'failed to delete myself (%s). am i already dead?'%self.utok 

    def _wiper(self):
        while True:
            if (datetime.datetime.now()-datetime.timedelta(seconds=self.MAX_POLL_IDLETIME))>(self.lastpoll):
                print 'gotta kill %s; last polled %s ago'%(self.utok,datetime.datetime.now()-self.lastpoll)
                self._kill()
            gevent.sleep(self.MAX_POLL_IDLETIME/2)
    def send(self,pkg):
        self._tosend.put(pkg)
    def read(self):
        return self._tosend.get()
    greenlets = {}
    def spawn(self,name,cb):
        if name not in self.greenlets:
            self.greenlets[name]=Greenlet.spawn(cb)
        else:
            print 'will not spawn already existing greenlet %s'%name
    def _protect_methods(self):
        for mn in dir(self):
            attr = getattr(self,mn)
            if not callable(attr): continue
            if mn.startswith('_'): continue
            raise Exception(mn)
    def __init__(self,utok):
        self._tosend =  queue.Queue()
        self.utok=utok
        self.lastpoll = datetime.datetime.now()
        self.spawn('wiper',self._wiper)
        

    lastpoll = None
    @action
    def poll(self,request):
        #print 'poll(): greenlets: %s'%self.greenlets
        item = self.read()
        if 'ident' in item and item['ident']!=self.utok:
            raise Exception('somehow my (%s) tosend gave me %s'%(self.utok,item))

        item['qsize']=self._tosend.qsize() #this is debug and can be removed
        rsp= Response('%s\n'%json.dumps(item))
        rsp.content_type='application/json'
        #gevent.sleep(1)
        self.lastpoll = datetime.datetime.now()

        return rsp

class IncrementorController(LongPollingHandler):
    stopped=False

    def increment(self):
        while not self.stopped:
            self.cnt+=1
            gevent.sleep(0.2)
            self.send({'number':self.cnt,'ident':self.utok})
    @action
    def putaction(self,request):
        self.send({'content':request.params.get('c'),'ident':self.utok})
        return XResponse({'result':'ok'})
    @action
    def stop(self,request):
        self.stopped=True
        self.kill_greenlets('incrementor')
        return XResponse({'result':'ok','value':self.stopped})
    def __init__(self,utok):
        #test specific
        LongPollingHandler.__init__(self,utok)
        self.cnt=0
        self.startincrementor()
    @action
    def startincrementor(self,request=None):
        self.stopped=False
        self.spawn('increment',self.increment)

        if request: return XResponse({'result':'ok','value':self.stopped})

    
connections={}
def longpolling(request,conn_info):
    global connections
    toks = conn_info.split('/')
    
    utok = toks[0]
    #print 'utok= %s'%utok
    if len(toks)>1:
        action = toks[1]
    else:
        action='poll'
    if utok not in connections:
        print 'initializing poller for the first time.'
        connections[utok] = IncrementorController(utok)
        print 'just instantiated a new longpoller. got %s so far.'%(len(connections))
    lp = connections[utok]
    #we do not allow calling internal methods at all.
    assert not action.startswith('_'),"security violation"
    f = getattr(lp,action)
    assert ".action_wrapper" in str(f),"%s is not allowed to be executed externally."%(action)

    return f(request)


#this is a demonstration of streaming
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

