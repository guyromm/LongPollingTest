from gevent import Greenlet,queue
import weakref
import datetime
from noodles.http import Response,XResponse
import json
import gevent
import hashlib

def action(f):
    "decorator to mark permitted actions as such."
    def action_wrapper(*args,**kw):
        return f(*args,**kw)

    return action_wrapper

def greenlet(f):
    "decorator to mark methods as greenlets."
    def greenlet_wrapper(*args,**kw):
        inst=args[0]
        name = f.__name__
        print 'greenlet_wrapper(%s). %s'%(name,inst)
        if not inst.greenlets: inst.greenlets = {} 
        if name not in inst.greenlets or inst.greenlets[name].successful():
            inst.greenlets[name]=Greenlet.spawn(f,inst)        
            print 'spawned a greenlet. now have %s'%len(inst.greenlets)
            #inst.greenlets[name].utok = inst.utok
        else:
            print 'will not spawn already existing greenlet %s'%name
        return f
    return greenlet_wrapper


#this is functionality common to both virtual channels and "connection" handlers
class GreenletMixin(object):
    """inherit from this to have a class instance that services greenlets."""
    greenlets = None
    channels={}
    _channel_instances=None
    def kill_greenlets(self,gn=None):
        #obtain the dict of greenlets we want to specifically kill
        if self.greenlets!=None:
            gt = dict([(gk,gl) for gk,gl in self.greenlets.items()\
                           if ((gn and gk==gn) or True)])
            gtv = gt.values()
            gtk = gt.keys()
            print 'beginning to kill %s greenlets'%(len(gtk))
        #do the killing
            gevent.killall(gtv,block=False)
        #del the dict references
            for gtkey in gtk: del self.greenlets[gtkey]
        else:
            print 'greenlets dict is uninitialized.'
    def close_channels(self,chtodel=None):
        print 'in close_channels()'
        if self._channel_instances!=None:
            for chn,ch in self._channel_instances.items():
                if chtodel and chn!=chtodel: continue
                print 'closing channel %s'%chn
                self._channel_instances[chn]._kill()
                del self._channel_instances[chn]


    def _kill(self):
        self.kill_greenlets()
        self.close_channels()
        

    @greenlet
    def _wiper(self):
        while True:
            if self.time_to_gc(): 
                self._kill()
                break
            gevent.sleep(self.MAXIDLE)
    

class RouterMixin(object):
    """implements routing within the longpolling transport."""
    connections={}
    LONGPOLLING_TOKEN_SALT='sdkj4kfkvnnnjk'

    @classmethod
    def _delconnections(cls,utok):
        try:
            del cls.connections[utok]
        except KeyError:
            print 'failed to delete myself (%s). am i already dead?'%self.utok 

    @classmethod
    def generate_token(cls,req,conn_info):
        """generate a unique 'connection' token"""
        while True:
            tok = (hashlib.md5(req.remote_addr+
                               str(datetime.datetime.now().microsecond)+
                               cls.LONGPOLLING_TOKEN_SALT).hexdigest()[0:8])
            if tok not in cls.connections: break
        cls.connections[tok]='PENDING'
        return XResponse({'result':'ok','token':tok})

    @classmethod
    def router(cls,request,conn_info):
        """entry point for everything in the long polling connection."""
        toks = conn_info.split('/')

        utok = toks[0]
        if utok=='_obtain_token':
            return cls.generate_token(request,conn_info)

        assert utok!='undefined',"bad token in %s"%conn_info
        assert utok in cls.connections,"utok %s not found in connections"%utok
        #print 'utok= %s'%utok
        if len(toks)==2 and toks[1]=='poll':
            chan=None
            action = 'poll'
        else:
            #if request.method=='POST':
            chan = toks[1]
            action = request.params.get('action')
            assert action!='undefined',"action is bad- %s"%request.params
            #else: raise Exception('bad method. toks: %s'%toks)

        if utok in cls.connections and cls.connections[utok]=='PENDING':
            print 'initializing poller for the first time.'
            cls.connections[utok] = cls(utok)
            print 'just instantiated a new longpoller. got %s.'%(len(cls.connections))

        conn = cls.connections[utok]
        #if the message is on a channel, route appropriately.
        if chan: 
            if chan not in conn._channel_instances:
                assert chan in conn.channels,"unknown channel %s."%(chan)
                raise Exception('channel uninitialized.')
            lp = conn._channel_instances[chan]
            assert lp.utok == conn.utok,"channel utok does not match connection utok %s != %s"%(lp.utok,conn.utok)
        else:
            lp = conn

        #we do not allow calling internal methods at all.
        assert not action.startswith('_'),"security violation"

        #print 'trying to obtain action %s from %s'%(action,chan)
        f = getattr(lp,action)
        if action!='poll':
            print 'obtained %s.%s.%s'%(utok,chan,action) 

        assert f.__name__== "action_wrapper","%s is not allowed to be executed externally."%(action)
        pkg = json.loads(request.params.get('pkg','{}'))
        if hasattr(lp,'onmessage'): lp.onmessage(pkg,request)

        return f(pkg,request)

class LPVirtSocket(GreenletMixin,RouterMixin):
    """base longpolling transport implementation."""
    MAX_POLL_IDLETIME=3
    MAXIDLE = 3
    #uninitialized queue
    _tosend = None

    def time_to_gc(self):
        rt= (datetime.datetime.now()-datetime.timedelta(seconds=self.MAX_POLL_IDLETIME))>(self.lastpoll)
        if rt and self.in_poll: rt=False
            
        if rt: 
            print 'gotta kill %s; last polled %s ago ; in_poll = %s'%(self.utok,datetime.datetime.now()-self.lastpoll,self.in_poll)
        return rt

    def _kill(self):
        GreenletMixin._kill(self)

        self._delconnections(self.utok)


    def send(self,chan,pkg):
        self._tosend.put({'chan':chan,'pkg':pkg})
    def read(self):
        return self._tosend.get()

    def __init__(self,utok):
        self._tosend =  queue.Queue()
        self.utok=utok
        self.lastpoll = datetime.datetime.now()
        self._channel_instances={}
        self._wiper()

        #instantiate the default handlers
        for chan in self.enabled_onstart:
            print('enabling channel %s'%chan)
            assert chan not in self._channel_instances
            self._channel_instances[chan]=self.channels[chan](chan,self,self.utok)
            assert self.utok==self._channel_instances[chan].utok

    lastpoll = None
    in_poll = False
    @action
    def poll(self,pkg,request):
        #print 'poll(): greenlets: %s'%self.greenlets
        self.in_poll=True
        try:
            item = self.read()
            if 'ident' in item and item['ident']!=self.utok:
                raise Exception('somehow my (%s) tosend gave me %s'%(self.utok,item))

        #item['qsize']=self._tosend.qsize() #this is debug and can be removed
            rsp= Response('%s\n'%json.dumps(item))
            rsp.content_type='application/json'
        #gevent.sleep(1)
            self.lastpoll = datetime.datetime.now()
            return rsp
        except:
            raise
        finally:
            self.in_poll=False




class LPHandler(GreenletMixin):
    """base handler class for a single LP communication channel."""
    greenlets=None
    
    def __init__(self,chan,sock,utok):
        #we are trying to encourage __del__ below.
        self.sockref = weakref.ref(sock)
        self.chan = chan
        self.utok = utok

    def __del__(self):
        print('LPHandler named %s is deleted'%self.chan)
    def send(self,msg):
        self.sockref().send(self.chan,msg)
    pass
