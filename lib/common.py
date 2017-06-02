# common functions that are used across classes...

from ConfigParser import ConfigParser
import base64
from Crypto.Cipher import AES
from Crypto import Random

class AESCipher:
	def __init__(self, key):
		self.key = key

	def encrypt(self, raw):
		raw = self.pad(raw)
		iv = Random.new().read(AES.block_size)
		cipher = AES.new(self.key, AES.MODE_CBC, iv)
		return base64.b64encode(iv + cipher.encrypt(raw)) 

	def decrypt(self, enc):
		enc = base64.b64decode(enc)
		iv = enc[:16]
		cipher = AES.new(self.key, AES.MODE_CBC, iv)
		return self.unpad(cipher.decrypt(enc[16:]))

	def pad(self, s):
		return s + (AES.block_size - len(s) % AES.block_size) * chr(AES.block_size - len(s) % AES.block_size)

	def unpad(self, s):
		return s[:-ord(s[len(s)-1:])]


def password_hash(section, pass_label, pass_hash_label):
	default_conf = ConfigParser()
	running_conf = ConfigParser()
	default_conf.add_section('GLOBAL')
	default_conf.set('GLOBAL', 'cipher_key', 'a916b62309c7a00ec332dc3388554033')
	default_conf.read(['./settings.conf'])

	cipher = AESCipher(default_conf.get('GLOBAL', 'cipher_key'))
	password = ''
	if default_conf.get(section, pass_label) != '':
		password = default_conf.get(section, pass_label)
		pass_hash = cipher.encrypt(default_conf.get(section, pass_label))
		default_conf.set(section, pass_hash_label, pass_hash)
		default_conf.set(section, pass_label, '')
		with open('./settings.conf', 'wb') as f:
			default_conf.write(f) # update the file to include the changes we have made
		# modify the running config to also reflect this change, but do it after settings so we don't push running config into 
		running_conf.read(['./running.conf'])
		if not running_conf.has_section(section):                                
			running_conf.add_section(section)
		running_conf.set(section, pass_hash_label, pass_hash)
		running_conf.set(section, pass_label, '')
		with open('./running.conf', 'wb') as f:
			running_conf.write(f) # update the file to include the changes we have made
	if password == '' and default_conf.get(section, pass_hash_label) != '':
		password = cipher.decrypt(default_conf.get(section, pass_hash_label))
	return password