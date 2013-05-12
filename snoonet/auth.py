from twisted.words.protocols import irc
from twisted.internet import reactor, protocol, threads
from twisted.python import log
import xmlrpclib as xmlrpc
import sys

class InvalidStatusCodeException(Exception):
    def __init__(self, message):
        self.message = message 
    def __str__(self):
        return repr(self.message)

class AuthBot:
    got_Pong = True

    def __init__(self):
        self.config = config
        self.nick = config.get('auth_bot', 'nick')
        self.passwd = config.get('auth_bot', 'passwd')
	self.source_ip = config.get('auth_bot', 'source_ip')
        self.channels = config.get('auth_bot', 'channels').split(', ')

    def xmlrpc_auth(self):
        self.server = xmlrpc.Server(self.server_url)
        result = self.server.atheme.login(self.nick, self.passwd)
        
        self.authcookie = result.authcookie

    def xmlrpc_send_command(service_name, command_name, *parameters):
        try:
            result = self.server.atheme.command(self.authcookie, self.nick, self.source_ip, service_name, command_name, *parameters)
        except xmlrpc.Fault as fault:
            if fault.faultCode is 4:
                return False
            elif fault.faultCode is 15:
                self.xmlrpc_auth()
                self.xmlrpc_send_command(service_name, command_name, *parameters)
            elif fault.faultCode is 12:
                pass
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
        return self.xmlrpc_send_command('chanserv', 'flags', channel, '+%s' % modes)

    def create_channel(self, channel, user):
        self.join(channel)
        self.say('ChanServ', 'REGISTER %s' %channel)

	while not self.is_channel_registered(channel):
		pass

	self.xmlrpc_send_command('ChanServ', 'ftransfer', channel, user)
        self.leave(channel)
    
    def validate_key(self, key):
        return self._rest_communicate('/key', key)        

    def expire_key(self, key):
        return self._rest_communicate('/use', key, {'status':'true'})

    def _rest_communicate(self, path, key, data=None):
        url = self.api_url + path
        try:    
            response = requests.get(url, params={'key':key}, data=data)
        except requests.RequestException as request_exception:
            log.err('Requests exception! key=%s, url=%s' %(key, url))
            raise request_exception
    
        if response.status_code is not 200:
            log.err('Response from Snoonet REST API: %s' % response.status_code)
            raise InvalidStatusCodeException('Invalid response code from REST API [%s].' % response.status_code)

        return response.json()

    def signedOn(self):
        for chan in self.channels:
            self.join(chan)

	self.say('NickServ', 'IDENTIFY %s' % self.passwd)

        xmlrpc_auth()

    def process_auth(self, user, channel, key):
        data = self.validate_key(key)

        subreddit_channel = '#' + data['channel']
        subreddit_name = data['subreddit']
        channel_mode = data['mode']

        if not self.is_channel_registered(subreddit_channel):
            self.create_channel(subreddit_channel, user, message="Registered channel for the %s subreddit" % subreddit_name)
        else:
            self.set_user_channel_modes(user, subreddit_channel, channel_mode)

        self.expire_key(key)

    def process_whisper(self, user, msg):
        split_message = msg.split()

        if len(split_message) != 2:
            self.say(user, "Invalid argument count.")
            return

        action = split_message[0]
        key = split_message[1]

        if action is not "subreddit_access":
            self.say(user, "Invalid action in first argument.")
            return
        try:
            if not self.is_key_valid(key):
                self.say(user, "Key not properly formed.")
                return

            if not self.is_user_registered(user):
                self.say(user, "You are not registered.")
                return

            self.process_auth(user, channel, key)

        except InvalidStatusCodeException, requests.RequestException) as api_exception:
            self.say(user, "Error communicating with Snoonet REST API.")
            raise api_exception
        except xmlrpc.Fault as fault:
            self.say(user, "Error communicating with Atheme services.")
            raise fault
        except:
            self.say(user, "Unknown error.")
            raise

    def privmsg(self, user, channel, msg):
        if channel == self.nick:
            self.process_whisper(user, msg)

class AuthBotFactory(protocol.ClientFactory):
    def __init__(self, config):
        self.config = config

    def buildProtocol(self, addr):
        return AuthBot(self.config)

    def clientConnectionLost(self, connector, reason):
        connector.connect()

    def clientConnectionFailed(self, connector, reason):
        reactor.stop()
        raise Exception('Connection failed: %s' % reason)

def start_auth_bot():
    log.startLogging(sys.stdout)

    config = ConfigParser.ConfigParser()
    config.read('auth_bot.cfg')

    factory = AuthBotFactory(config)

    log.msg('Connecting...')
    host = config.get('auth_bot', 'irc_server')
    port = int(config.get('auth_bot', 'irc_server_port'))
    reactor.connectTCP(config.get(host), port, factory)
    reactor.run()
