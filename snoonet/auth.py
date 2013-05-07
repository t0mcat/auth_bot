"""
TODO:
    * Consolidate atheme command code
    * Create config file with correct values (don't forget /xmlrpc on URL!)
    * Clean up logging code
    * consolidate HTTP requests code
    * Catch Fault 15 (Invalid authcookie for this account)
"""

from twisted.words.protocols import irc
from twisted.internet import reactor, protocol, threads
from twisted.python import log
import sys

class AuthBot:
    got_Pong = True

    def __init__(self):
        self.config = config
        self.nick = config.get('auth_bot', 'nick')
        self.passwd = config.get('auth_bot', 'passwd')
        self.channels = config.get('auth_bot', 'channels').split(', ')

    def xmlrpc_auth(self):
        self.server = xmlrpc.Server(self.server_url)
        result = self.server.atheme.login(self.nick, self.passwd)
        self.authcookie = result.authcookie

    def is_key_valid(self, key):
        allowed_set = set(string.uppercase + string.lowercase + string.digits)
        return all(x in allowed_set for x in key) and len(key) is 25

    def is_user_registered(self, username):
        try:
            result = self.server.atheme.command(self.authcookie, self.user, self.source_ip, 'nickserv', 'info', username)

        except xmlrpclib.Fault as fault:
            if fault.faultCode is 4:
                return False
            else:
                raise fault

        return True

    def is_channel_registered(self, channel):
        try:
            result = self.server.atheme.command(self.authcookie, self.user, self.source_ip, 'chanserv', 'info', channel)
        except xmlrpclib.Fault as fault:
            if fault.faultCode is 4:
                return False
            else:
                raise fault

        return True

    def set_user_channel_modes(self, user, channel, modes):
        try:
            self.server.atheme.command(self.authcookie, self.user, self.source_ip, 'chanserv', 'flags', channel, '+%s' % modes)
        except xmlrpclib.Fault as fault:
            if fault.faultCode is 12:
                return True
            else:
                raise fault

        return True

    def create_channel(self, channel, user):
        self.join(channel)
        self.say('ChanServ', 'REGISTER %s' %channel)
        self.server.atheme.command(self.authcookie, self.nick,'127.0.0.1','ChanServ', 'ftransfer', channel, user)
        self.leave(channel)

    def signedOn(self):
        for chan in self.channels:
            log.msg('Joining channel ' + chan)

        xmlrpc_auth()

    def privmsg(self, user, channel, msg):
        if channel == self.nick:
            log.msg('Msg received from %s' % user)
            split_message = msg.split()

            if len(split_message) != 2:
                self.say(user, "Invalid argument count.")
                return

            action = split_message[0]
            key = split_message[1]

            if action is not "subreddit_access":
                self.say(user, "Invalid action in first argument.")
                return

            if not self.is_key_valid(key):
                self.say(user, "Key not properly formed.")
                return

            if not self.is_user_registered(user):
                self.say(user, "You are not registered.")
                return

            url = 'http://api.snoonet.org/api/v1/modekey/key'
            response = requests.get(url, params={'key':key})

            if response.status_code is not 200:
                self.say(user, "Error getting response back from auth server.")
                log.err('non-200 response received from auth server.  Actual status code was %s' % response.status_code)
                return

            data = response.json()
            subreddit_channel = '#' + data['channel']
            subreddit_name = data['subreddit']
            channel_mode = data['mode']

            if not self.is_channel_registered(subreddit_channel):
                self.create_channel(subreddit_channel, user, message="Registered channel for the %s subreddit" % subreddit_name)
            else:
                self.set_user_channel_modes(user, subreddit_channel, channel_mode)

            post_url = 'http://api.snoonet.org/api/v1/modekey/use'
            post_data = {'status':'true'}
            response = requests.post(post_url, data=post_data, params={'use':key})

            if response.status_code is not 200:
                log.err('non-200 response received from auth server.  Actual status code was %s' % response.status_code)

            self.say(user, "Success! :)")

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
