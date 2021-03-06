#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
#  Copyright (C) 2011 Fabrizio Tarizzo <fabrizio@fabriziotarizzo.org>
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.

import sys
import os
import csv
import re

__author__    = "Fabrizio Tarizzo <fabrizio@fabriziotarizzo.org>"
__copyright__ = "Copyright (c) 2011 Fabrizio Tarizzo"
__license__   = "GNU General Public License version 3 or later"

class Key:
	def __init__ (self, keyid, keylen, flags, created, expire, pkalgo, keyversion):
		self.keyid      = keyid
		self.keylen     = keylen
		self.created    = created
		self.expire     = expire
		self.pkalgo     = pkalgo
		self.keyversion = keyversion
		self.flags      = flags
		self.status     = '?'
		self.valid_uids = 0
		
		self.expired = False
		self.revoked = False
		self.revoker = ''
		if 'e' in flags:
			self.expired = True
			self.status  = 'E'
		if 'r' in flags:
			self.revoked = True
			self.status  = 'R'

		self.uids = []
		self.signatures = {}
		self.primary_uid = None
		self.most_recent_selfsig = None
		
	def __str__ (self):
		mrs = self.most_recent_selfsig
		if not mrs:
			return  "%s;%s;%d;%d;%s;%s;%d;%d;;;;;;;%s" % \
				(self.status, self.keyid, self.pkalgo, self.keylen,
				 self.created, self.expire, self.keyversion, self.valid_uids,
				 self.primary_uid)
		else:
			return  "%s;%s;%d;%d;%s;%s;%d;%d;%s;%s;%s;%d;%d;%d;%s" % \
				(self.status, self.keyid, self.pkalgo, self.keylen,
				 self.created, self.expire, self.keyversion, self.valid_uids,
				 mrs.date, mrs.expire, mrs.flags, mrs.pkalgo, mrs.hashalgo,
				 mrs.version, self.primary_uid)

	def add_uid (self, uid):
		self.uids.append (uid)
		if self.primary_uid == None:
			self.primary_uid = uid
		
	def commit (self):
		self.valid_uids = 0
		for uid in self.uids:
			uid.commit()
			#Don't count revoked and non-selfsigned user ids
			if not (uid.revoked) and uid.most_recent_selfsig:
				self.__add_signature (uid.most_recent_selfsig)
				if uid.most_recent_selfsig.is_valid():
					self.valid_uids += 1
					if uid.is_primary:
						self.primary_uid = uid
						
					for k in uid.signatures:
						self.__add_signature (uid.signatures[k])
					
		if self.status == '?':
			if self.most_recent_selfsig and self.most_recent_selfsig.is_valid():
				self.status = 'V'
			else:
				self.status = 'I'

	def __add_signature (self, sig):
		issuer = sig.issuer
		if issuer == self.keyid:
			if not self.most_recent_selfsig:
				self.most_recent_selfsig = sig
			elif not (self.most_recent_selfsig.is_valid()) and sig.is_valid():
				self.most_recent_selfsig = sig
			elif self.most_recent_selfsig.date < sig.date and sig.is_valid():
				self.most_recent_selfsig = sig
		else:
			if sig.is_valid() and (not issuer in self.signatures or self.signatures[issuer].date < sig.date):
				self.signatures[issuer] = sig
                
class Signature:
	__exclude_expired = False
	__exclude_revoked = False
	__exclude_deprecated_hashalgos = False
	__deprecated_hashalgos = []
	
	@classmethod
	def set_validity_requirements (cls, **kwargs):
		cls.__exclude_expired = kwargs.get ('exclude_expired', False)
		cls.__exclude_revoked = kwargs.get ('exclude_revoked', False)
		cls.__exclude_deprecated_hashalgos = kwargs.get ('exclude_deprecated_hashalgos', False)
		cls.__deprecated_hashalgos = kwargs.get ('deprecated_hashalgos', [])
		
	def __init__ (self, issuer, date, expire, level, flags, version, pkalgo, hashalgo):
		self.issuer   = issuer
		self.date     = date
		self.expire   = expire
		self.level    = level
		self.flags    = flags
		self.version  = version
		self.pkalgo   = pkalgo
		self.hashalgo = hashalgo
		
		self.expired  = False
		self.revoked  = False
		if 'e' in flags:
			self.expired = True
			
	def is_valid (self):
		if Signature.__exclude_revoked and self.revoked:
			return False
		if Signature.__exclude_expired and self.expired:
			return False
		if Signature.__exclude_deprecated_hashalgos and self.hashalgo in Signature.__deprecated_hashalgos:
			return False
			
		return True
			
	def __str__ (self):
		return "%s;%s;%s;%s;%d;%d;%d;%d" % \
			(self.issuer, self.date, self.expire, self.flags, self.level, self.pkalgo, self.hashalgo, self.version)
		
class Uid:
	def __init__ (self, key, userid):
		self.userid  = userid
		self.key     = key
		self.revoked = False
		
		self.is_primary  = False
		self.signatures  = {}
		self.revocations = {}
		self.most_recent_selfsig = None
		
	def add_revocation (self, rev):
		issuer = rev.issuer
		if issuer == self.key.keyid:
			if rev.revtype == 0x20:
				self.key.revoked = True   # Should already be marked as revoked!
				self.key.status  = 'Ro'   # Revoked by Owner
				self.key.revoker = issuer
			elif rev.revtype == 0x30:
				self.revoked = True
		else:
			if rev.revtype == 0x20:
				self.key.revoked = True   # Should already be marked as revoked!
				self.key.status  = 'Rd'   # Revoked by a Designated revoker
				self.key.revoker = issuer
			elif rev.revtype == 0x30 and (not issuer in self.revocations or self.revocations[issuer].date < rev.date):
				self.revocations[issuer] = rev
		
	def __set_mrs (self, sig):
		self.most_recent_selfsig = sig
		if 'p' in sig.flags:
			self.is_primary = True
			
	def __str__ (self):
		return self.userid
					
	def add_signature (self, sig):
		issuer = sig.issuer
		if issuer == self.key.keyid:
			#if not self.most_recent_selfsig or self.most_recent_selfsig.date < sig.date:
			#	self.most_recent_selfsig = sig
			if not self.most_recent_selfsig:
				self.__set_mrs (sig)
			elif not (self.most_recent_selfsig.is_valid()) and sig.is_valid():
				self.__set_mrs (sig)
			elif self.most_recent_selfsig.date <= sig.date and sig.is_valid():
				self.__set_mrs (sig)
		else:
			if sig.is_valid() and (not issuer in self.signatures or self.signatures[issuer].date < sig.date):
				self.signatures[issuer] = sig
				
	def commit (self):
		for rev_issuer in self.revocations:
			if rev_issuer in self.signatures and self.signatures[rev_issuer].date < self.revocations[rev_issuer].date:
				self.signatures[rev_issuer].revoked = True

class Revocation:
	def __init__ (self, issuer, date, revtype, version, pkalgo, hashalgo):
		self.issuer   = issuer
		self.date     = date
		self.revtype  = revtype
		self.version  = version
		self.pkalgo   = pkalgo
		self.hashalgo = hashalgo

def do_key (key, outfiles):
	key.commit()
	print >>outfiles['keystatus'], "%s" % key
	
	if key.status == 'V' and key.signatures:
		print >>outfiles['preprocessed'], "p%s" % key.keyid
		for s in key.signatures:
			print >>outfiles['preprocessed'], "s%s" % key.signatures[s]

if __name__ == '__main__':
	key  = None
	keycount = 0
	
	datadir  = sys.argv[1]
	
	# TODO make these configurable by command line options
	exclude_expired_keys = True
	exclude_expired_sigs = True
	exclude_revoked_keys = True
	exclude_revoked_sigs = True
	exclude_deprecated_hashalgos = False
	deprecated_hashalgos = []
	
	Signature.set_validity_requirements (
		exclude_expired = exclude_expired_sigs,
		exclude_revoked = exclude_revoked_sigs,
		exclude_deprecated_hashalgos = exclude_deprecated_hashalgos,
		deprecated_hashalgos = deprecated_hashalgos
	)

	# 1st pass
	infile   = file (os.path.join (datadir, 'pgpring.dump'), 'r')
	outfiles = {
		'preprocessed': file (os.path.join (datadir, 'preprocessed.tmp'), 'w'),
		'keystatus'   : file (os.path.join (datadir, 'keystatus.csv.tmp'), 'w')
	}
	interesting_keys = set()
	policy_uris = {}
	for line in infile:

		fields = line.strip().split(':')
		rectype = fields[0]
		if rectype == 'pub':
			if key:
				do_key (key, outfiles)
				if key.status == 'V' and key.signatures:
					interesting_keys.add (key.keyid)

			flags   = fields[1]
			keylen  = int(fields[2])
			pkalgo  = int(fields[3])
			keyid   = fields[4]
			created = fields[5]
			expire  = fields[6]
			keyver  = int(fields[7])

			key = Key (keyid, keylen, flags, created, expire, pkalgo, keyver)
			keycount += 1
			if (keycount % 100000) == 0:
				print >>sys.stderr, "%d keys done, %d interesting." % (keycount, len (interesting_keys))
			
		elif rectype == 'uid':
		    uid = Uid (key, fields[9])
		    key.add_uid (uid)
		    
		elif rectype == 'sig':
			issuer   = fields[1]
			date     = fields[2]
			expire   = fields[3]
			level    = int(fields[4], 16) - 0x10
			flags    = fields[5]
			version  = int(fields[6])
			pkalgo   = int(fields[7])
			hashalgo = int(fields[8])

			sig = Signature (issuer, date, expire, level, flags, version, pkalgo, hashalgo)
			uid.add_signature(sig)
		
		elif rectype == 'rev':
			issuer   = fields[1]
			date     = fields[2]
			revtype  = int(fields[4], 16)
			version  = int(fields[6])
			pkalgo   = int(fields[7])
			hashalgo = int(fields[8])
			
			rev = Revocation (issuer, date, revtype, version, pkalgo, hashalgo)
			uid.add_revocation (rev)
			
		elif rectype == 'spk':
			if not sig.is_valid():
				continue
				
			pktype = int (fields[1])
			flags  = int (fields[2])
			pklen  = int (fields[3])
			pkdata = fields[4].decode('string_escape')
			issuer = sig.issuer
			signee = key.keyid
			if pktype == 26:
				# Certification policy URI
				
				#Ignore self signatures
				if signee == issuer:
					continue
				
				if not issuer in policy_uris:
					policy_uris[issuer] = {}
					
				# Handle special cases
				if pkdata == 'string':
					continue
				if pkdata[0] in ('"', "'"):
					pkdata = pkdata[1:]
				if pkdata[-1] in ('"', "'"):
					pkdata = pkdata[:-1]
					
				if pkdata not in policy_uris[issuer]:
					policy_uris[issuer][pkdata] = {'signees': set(), 'last_used': '0000-00-00'}
				policy_uris[issuer][pkdata]['signees'].add(signee)
				if policy_uris[issuer][pkdata]['last_used'] < sig.date:
					policy_uris[issuer][pkdata]['last_used'] = sig.date

	do_key (key, outfiles)
	print >>sys.stderr, "%d keys done, %d interesting." % (keycount, len (interesting_keys))
	if key.status == 'V' and key.signatures:
		interesting_keys.add (keyid)
	
	infile.close()
	for f in outfiles:
		outfiles[f].close()
		
	# 2nd Pass
	infiles = {
		'preprocessed': file (os.path.join (datadir, 'preprocessed.tmp'), 'r'),
		'keystatus'   : file (os.path.join (datadir, 'keystatus.csv.tmp'), 'r')
	}
	outfiles = {
		'preprocessed': file (os.path.join (datadir, 'preprocessed'), 'w'),
		'keystatus'   : file (os.path.join (datadir, 'keystatus.csv'), 'w'),
		'policyuris'  : file (os.path.join (datadir, 'policyuris.csv'), 'w')
	}
	
	keyid = ''
	signatures = set()
	trusted_keys = set()
	done = set()
	for line in infiles['preprocessed']:
		line = line.strip()
		if line[0] == 'p':
			if keyid and (keyid[1:] in interesting_keys) and (keyid[1:] not in done) and signatures:
				trusted_keys.add(keyid[1:])
				done.add(keyid[1:])
				print >>outfiles['preprocessed'], keyid
				for s in signatures:
					print >>outfiles['preprocessed'], s
				
			keyid = line
			signatures = set()
		elif line[0] == 's':
			fields = line.split(';')
			issuer = fields[0][1:]
			if issuer in interesting_keys:
				signatures.add(line)
	
	if keyid and signatures:
		trusted_keys.add(keyid[1:])
		print >>outfiles['preprocessed'], keyid
		for s in signatures:
			print >>outfiles['preprocessed'], s
	
	names = {}
	for line in infiles['keystatus']:
		line   = line.strip()
		fields = line.split(';')
		keyid  = fields[1]
		status = fields[0]
		name   = fields[14]
		
		if keyid in policy_uris:
			names[keyid] = name
			
		if status != 'V' or (keyid not in trusted_keys):
			print >>outfiles['keystatus'], line
		else:
			fields[0] = 'VC'
			print >>outfiles['keystatus'], ';'.join(fields)
	
	removemail = lambda s: re.sub ('<.*>', '', s).strip()
	getname = lambda k: removemail (names.get(k, '').decode('string_escape'))
	for s in sorted (policy_uris.keys(), key = getname):
		if s in interesting_keys:
			for p in policy_uris[s]:
				pu = policy_uris[s][p]
				print >>outfiles['policyuris'], '%s;%s;%s;%d;%s' % (s, getname(s), p, len(pu['signees']), pu['last_used'])

	for f in infiles:
		infiles[f].close()
	for f in outfiles:
		outfiles[f].close()
		
	os.remove (os.path.join (datadir, 'preprocessed.tmp'))
	os.remove (os.path.join (datadir, 'keystatus.csv.tmp'))

