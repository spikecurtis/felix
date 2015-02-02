# -*- coding: utf-8 -*-
# Copyright 2014 Metaswitch Networks
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
felix.fiptables
~~~~~~~~~~~~

IP tables management functions. This is a wrapper round python-iptables that
allows us to mock it out for testing.
"""
import logging
import os
import re
import time

from calico.felix import futils
from calico.felix.futils import IPV4, IPV6

from collections import namedtuple
#*****************************************************************************#
#* The following is so that rule.target.name can be used to identify rules;  *#
#* this is the subset of the Target object from iptc that is actually        *#
#* required by calling code.                                                 *#
#*****************************************************************************#
RuleTarget = namedtuple('RuleTarget', ['name'])

# Logger
log = logging.getLogger(__name__)

# Special value to mean "put this rule at the end".
RULE_POSN_LAST = -1

class Rule(object):
    """
    Fake rule object.
    """
    def __init__(self, type, target_name=None):
        self.type = type

        self.target = RuleTarget(target_name)
        self.protocol = None
        self.src = None
        self.in_interface = None
        self.out_interface = None

    def create_target(self, name, parameters=None):
        pass

    def create_tcp_match(self, dport):
        pass

    def create_icmp6_match(self, icmp_type):
        pass

    def create_conntrack_match(self, state):
        pass

    def create_mark_match(self, mark):
        pass

    def create_mac_match(self, mac_source):
        pass

    def create_set_match(self, match_set):
        pass

    def create_udp_match(self, sport, dport):
        pass

    def __eq__(self, other):
        return False

    def __ne__(self, other):
        return True


def insert_rule(rule, chain, position=0, force_position=True):
    pass

def get_table(type, name):
    return Table(type, name)

def get_chain(table, name):
    return Chain(name)


class Chain(object):
    def __init__(self, name):
        self.name = name
        self.rules = []
        self.type = None # Not known until put in table.

    def flush(self):
        pass

    def delete_rule(self, rule):
        # The rule must exist or it is an error.
        pass

    def __eq__(self, other):
        # Equality deliberately only cares about name.
        if self.name == other.name:
            return True
        else:
            return False

    def __ne__(self, other):
        return not self.__eq__(self,other)


class Table(object):
    """
    Mimic of an IPTC table.
    """
    def __init__(self, type, name):
        self.type = type
        self.name = name

    def is_chain(self, name):
        return False

    def delete_chain(self, name):
        pass
                
    @property
    def chains(self):
        # Only used when listing chains; OK to just return nothing
        return []

