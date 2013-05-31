from twisted.words.protocols import irc
from twisted.internet import reactor, protocol, threads
from twisted.python import log
import xmlrpclib as xmlrpc
import ConfigParser
import requests
import string
import sys

class InvalidStatusCodeException(Exception):
    def __init__(self, message):
        self.message = message 
    def __str__(self):
        return repr(self.message)

class AuthBot(irc.IRCClient):
    got_Pong = True

    def __init__(self, config, log):
        self.config = config
        self.nickname = config.get('auth_bot', 'nick')
        self.passwd = config.get('auth_bot', 'passwd')
        self.source_ip = config.get('auth_bot', 'source_ip')
        self.channels = config.get('auth_bot', 'channels').split(', ')
        self.xmlrpc_url = "http://%s:%s/xmlrpc" % (config.get('auth_bot', 'xmlrpc_server'), config.get('auth_bot', 'xmlrpc_server_port'))
	self.api_url = config.get('auth_bot', 'api_url')
        self.log = log

        self.channels_to_give = {}

    def xmlrpc_auth(self):
        self.log.msg("Starting XMLRPC auth.")
        self.server = xmlrpc.Server(self.xmlrpc_url)
        result = self.server.atheme.login(self.nickname, self.passwd)
        
        self.log.msg("XMLRPC auth complete. Result: %s" % result)

        if len(result) != 20:
            raise Exception("Error authing with XMLRPC.")

        self.authcookie = result

    def xmlrpc_send_command(self, service_name, command_name, *parameters):
        try:
            result = self.server.atheme.command(self.authcookie, self.nickname, self.source_ip, service_name, command_name, *parameters)
        except xmlrpc.Fault, fault:
            self.log.msg('Fault: %s' % fault.faultString)

            if fault.faultCode is 4:
                return False
            elif fault.faultCode is 15:
                self.xmlrpc_auth()
                self.xmlrpc_send_command(service_name, command_name, *parameters)
            elif fault.faultCode is 12:
                return "Already in requested state."
            else:
                raise fault

        return True

    def is_key_valid(self, key):
        allowed_set = set(string.uppercase + string.lowercase + string.digits)
        return all(x in allowed_set for x in key) and len(key) is 25

    def is_user_registered(self, username):
        return self.xmlrpc_send_command('nickserv', 'info', username)

    def is_channel_registered(self, channel):
        return self.xmlrpc_send_command('chanserv', 'info', channel)

    def set_user_channel_modes(self, user, channel, modes):
        response = self.xmlrpc_send_command('chanserv', 'FFLAGS', channel, user, modes)
        if isinstance(response, str):
            self.msg(user, "You already have operator access to the channel. If you are having problems or if you have any questions, type /join #help and let a staff member know.")
            return True

        return response

    def create_channel(self, channel, user):
        #current race condition exists here when multiple users request the same channel simultaneously
        self.channels_to_give[str(channel)] = [user] 

        self.log.msg("Channel: %s" % channel)
        self.join(str(channel))

    #will always attempt to grab oper in any channel it joins
    def joined(self, channel):
        self.log.msg("Joined channel %s, taking op." % channel)
        self.msg('operserv', str('mode %s +o %s' % (channel, self.nickname)))

    #will always attempt to register any channel it is given oper in
    def modeChanged(self, user, channel, set, modes, args):
        self.log.msg("MODECHANGE: user=%s, channel=%s, set=%s, modes=%s, args=%s" % (user, channel, set, modes, args))
        if args[0] == self.nickname and 'o' in modes and set == True:
            if not self.is_channel_registered(channel):
                self.log.msg("attempting to register %s" % channel)
                self.msg('ChanServ', str('REGISTER %s' % channel))
        #will always leave channel where it loses oper
        if args[0] == self.nickname and 'o' in modes and set == False:
            self.leave(str(channel))
        if args[0] == 'ChanServ' and 'o' in modes and set == True:
            #will always drop oper in channel when ChanServ joins
            self.msg('operserv', str('mode %s -o %s' % (channel, self.nickname)))

            if channel in self.channels_to_give.keys():
               for user in self.channels_to_give[channel]:
                   self.log.msg('starting ftransfer of channel %s to user %s' % (channel, user))
                   self.xmlrpc_send_command('ChanServ', 'ftransfer', channel, user)
                   self.msg(user, "You've successfully been granted operator access to {0}. To join, type /join {0}. If you have any questions, type /join #help, ask your question(s),  and someone will gladly provide assistance.".format(channel))

    def validate_key(self, key):
        return self._rest_communicate('/', key)        

    def expire_key(self, key):
        return self._rest_communicate('/use', key, {'status':'true'})

    def _rest_communicate(self, path, key, data=None):
        url = self.api_url + '/api/v1/modekey' + path
        try:    
            response = requests.get(url, params={'key':key}, data=data)
        except requests.RequestException as request_exception:
            self.log.err('Requests exception! key=%s, url=%s' %(key, url))
            raise request_exception
    
        if response.status_code is not 200:
            self.log.err('Response from Snoonet REST API: %s' % response.status_code)
            raise InvalidStatusCodeException('Invalid response code from REST API [%s].' % response.status_code)

        return response.json()

    def signedOn(self):
        for chan in self.channels:
            self.log.msg('joining %s.' % chan) 
            self.join(chan)

        self.msg('NickServ', 'IDENTIFY %s' % self.passwd)

        self.xmlrpc_auth()

    def process_auth(self, user, channel, key):
        data = self.validate_key(key)

        subreddit_channel = '#' + data['channel']
        subreddit_name = data['subreddit']
        channel_mode = data['mode']

        if not self.is_channel_registered(subreddit_channel):
            self.create_channel(subreddit_channel, user)
        else:
            self.set_user_channel_modes(user, subreddit_channel, channel_mode)

        self.log.msg(self.expire_key(key))

    def process_whisper(self, user, msg):
        user = user.split('!')[0]
        split_message = msg.split()

        if len(split_message) != 2:
            self.msg(user, "Invalid argument count.")
            return

        action = split_message[0]
        key = split_message[1]

        if action != "subreddit_access":
            self.msg(user, "Invalid action in first argument.")
            return

        self.log.msg('subreddit_access request received from %s.' % user)

        try:
            if not self.is_key_valid(key):
                self.log.msg('Key not properly formed.')
                self.msg(user, "Key not properly formed.")
                return

            if not self.is_user_registered(user):
                self.log.msg('You are not registered.')
                self.msg(user, "You are not registered.")
                return

            response = self.validate_key(key)
            channel = response['channel']

            self.process_auth(user, str(channel), key)

        except (InvalidStatusCodeException, requests.RequestException), api_exception:
            self.log.err()
            self.msg(user, "Error communicating with Snoonet REST API.")
            raise api_exception
        except xmlrpc.Fault as fault:
            self.log.err()
            self.msg(user, "Error communicating with Atheme services.")
            raise fault
        except:
            self.log.err()
            self.msg(user, "Unknown error.")
            raise

    def privmsg(self, user, channel, msg):
        if channel == self.nickname:
            self.log.msg('Received whisper from %s' % user)      
            self.process_whisper(user, msg)

class AuthBotFactory(protocol.ClientFactory):
    def __init__(self, config, log):
        self.config = config
        self.log = log

    def buildProtocol(self, addr):
        return AuthBot(self.config, self.log)

    def clientConnectionLost(self, connector, reason):
        self.log.msg('Connection lost.')
        self.log.msg(reason)
        connector.connect()

    def clientConnectionFailed(self, connector, reason):
        self.log.msg('Connection failed.')
        self.log.msg(reason)
        connector.connect()

def start_auth_bot():
    log.startLogging(sys.stdout)

    config = ConfigParser.ConfigParser()
    config.read('auth_bot.cfg')

    factory = AuthBotFactory(config, log)

    log.msg('Connecting...')
    host = config.get('auth_bot', 'irc_server')
    port = int(config.get('auth_bot', 'irc_server_port'))
    reactor.connectTCP(host, port, factory)
    reactor.run()
