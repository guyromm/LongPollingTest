# -*- coding: utf-8 -*-
'''
filedesc: default controller file
'''
from noodles.http import Response,XResponse
import json

def index(request):
    return Response('<h1>Hello, NoodlesFramework!</h1>')

import datetime,time
from gevent import Greenlet,queue


def current_time(body):
    current = start = datetime.datetime.now()
    end = start + datetime.timedelta(seconds=60)

    while current < end:
        current = datetime.datetime.now()
        body.put('%s\n' % current.strftime("%Y-%m-%d %I:%M:%S"))
        time.sleep(1)

    body.put('all done\n')
    body.put(StopIteration)



class LongPoller(object):
    tosend = queue.Queue()
    stopped=False
    def increment(self):
        while not self.stopped:
            self.cnt+=1
            time.sleep(0.2)
            self.tosend.put({'number':self.cnt,'ident':self.utok})
    def startincrementor(self,request=None):
        self.stopped=False
        self.g = Greenlet.spawn(self.increment)
        if request: return XResponse({'result':'ok','value':self.stopped})
    def __init__(self,utok):
        self.cnt=0
        self.utok=utok
        self.startincrementor()

    def poll(self,request):

        item = self.tosend.get()
        item['qsize']=self.tosend.qsize()
        rsp= Response('%s\n'%json.dumps(item))
        rsp.content_type='application/json'
        #time.sleep(1)
        return rsp
    def putaction(self,request):
        self.tosend.put({'content':request.params.get('c'),'ident':self.utok})
        return XResponse({'result':'ok'})
    def stop(self,request):
        self.stopped=True
        return XResponse({'result':'ok','value':self.stopped})
connections={}
def longpolling(request,conn_info):
    global connections
    toks = conn_info.split('/')
    
    utok = toks[0]
    print 'utok= %s'%utok
    if len(toks)>1:
        action = toks[1]
    else:
        action='poll'
    if utok not in connections:
        print 'initializing poller for the first time.'
        connections[utok] = LongPoller(utok)
    lp = connections[utok]
    return getattr(lp,action)(request)

    raise Exception(conn_info)

from noodles.websocket.streaming import StreamQueue ,PartialResponse
def streamer(request,conn_id):
    resp = PartialResponse()
    resp.content_type='text/plain'
    body = StreamQueue(resp)
    body.put(' '*1000)
    body.put('current time:\n')

    g = Greenlet.spawn(current_time,body)

    return body
