# -*- coding: utf-8 -*-
#
# Copyright (c) 2015 Metaswitch Networks
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

# Etcd-based transport for the Calico/OpenStack Plugin.

# Standard Python library imports.
import etcd
import eventlet
import json
import re
import time

# Calico imports.
from calico.openstack.transport import CalicoTransport

LOG = None


class CalicoTransportEtcd(CalicoTransport):
    """Calico transport implementation based on etcd."""

    OPENSTACK_ENDPOINT_RE = re.compile(
    r'^/calico/host/(?P<hostname>[^/]+)/.*openstack.*/endpoint/(?P<endpoint_id>[^/]+)')

    def __init__(self, driver, logger):
        super(CalicoTransportEtcd, self).__init__(driver)

        # Initialize logger.
        global LOG
        LOG = logger

    def initialize(self):
        # Prepare client for accessing etcd data.
        self.client = etcd.Client()

        # Spawn a green thread for periodically resynchronizing etcd against
        # the OpenStack database.
        eventlet.spawn(self.periodic_resync_thread)

    def periodic_resync_thread(self):
        while True:
            try:
                # Resynchronize endpoint data.
                needed_profiles = self.resync_endpoints()

                # Resynchronize security group data.
                self.resync_security_groups(needed_profiles)

                # Sleep until time for next resync.
                eventlet.sleep(PERIODIC_RESYNC_INTERVAL_SECS)

            except:
                LOG.exception("Exception in periodic resync thread")

    def resync_endpoints(self):
        # Get all current endpoints from the OpenStack database and key them on
        # endpoint ID.
        ports = {}
        for port in self.driver.get_endpoints():
            ports[port['id']] = port

        # As we go through the current endpoints, we'll accumulate the set of
        # security profiles that they need.  So start with an empty list here.
        needed_profiles = set()

        # Read all etcd keys under /calico/host.
        r = client.read('/calico/host', recursive=True)
        for child in r.children:
            m = OPENSTACK_ENDPOINT_RE.match(child.key)
            if m:
                # We have a key/value pair for an OpenStack endpoint.  Extract
                # the endpoint ID and hostname from the key, and read the JSON
                # data as a dict.
                endpoint_id = m.group("endpoint_id")
                hostname = m.group("hostname")
                data = json_decoder.decode(child.value)

                if (endpoint_id in ports and
                    hostname == ports[endpoint_id]['binding:host_id'] and
                    data == self.port_etcd_data(ports[endpoint_id])):
                    # OpenStack still has an endpoint that exactly matches this
                    # etcd key/value.  Remember its security profile.
                    needed_profiles.add(data['profile_id'])

                    # No change is needed to the etcd data, and we can delete
                    # the port from the ports dict so as not to unnecessarily
                    # write out its (unchanged) value again below.
                    del ports[endpoint_id]

                elif (endpoint_id not in ports or
                      hostname != ports[endpoint_id]['binding:host_id']):
                    # OpenStack no longer has an endpoint with the ID in the
                    # etcd key; or it does, but the endpoint has migrated to a
                    # different host than the one in the etcd key.  In both
                    # cases the etcd key is no longer valid and should be
                    # deleted.  In the migration case, data will be written
                    # below to an etcd key that incorporates the new hostname.
                    client.delete(child.key)

        # Now write etcd data for any endpoints remaining in the ports dict;
        # these are new endpoints - i.e. never previously represented in etcd
        # data - or endpoints that have migrated or whose data has changed.
        for port in ports.values:
            data = self.port_etcd_data(port)
            client.write(self.port_etcd_key(port), data)

            # Remember the security profile that this port needs.
            needed_profiles.add(data['profile_id'])

        return needed_profiles

    def port_etcd_key(self, port):
        return "/calico/host/%s/workload/openstack/endpoint/%s" % (
            port['binding:host_id'],
            port['id']
        )

    def port_etcd_data(self, port):
        # Construct the simpler port data.
        data = {'state': 'active' if port['admin_state_up'] else 'inactive',
                'name': port['interface_name'],
                'mac': port['mac_address'],
                'profile_id': self.port_profile_id(port)}

        # Collect IPv6 and IPv6 addresses.  On the way, also set the
        # corresponding gateway fields.  If there is more than one IPv4 or IPv6
        # gateway, the last one (in port['fixed_ips']) wins.
        ipv4_nets = []
        ipv6_nets = []
        for ip in port['fixed_ips']:
            if ':' in ip['ip_address']:
                ipv6_nets.append(ip['ip_address'] + '/128')
                if ip['gateway'] is not None:
                    data['ipv6_gateway'] = ip['gateway']
            else:
                ipv4_nets.append(ip['ip_address'] + '/32')
                if ip['gateway'] is not None:
                    data['ipv4_gateway'] = ip['gateway']
        data['ipv4_nets'] = ipv4_nets
        data['ipv6_nets'] = ipv6_nets

        # Return that data.
        return data

    def port_profile_id(self, port):
        return '_'.join(port['security_groups'])

    def resync_security_groups(self, needed_profiles):
        # Get all current security groups from the OpenStack database and key
        # them on security group ID.
        sgs = {}
        for sg in self.driver.get_security_groups():
            sgs[sg['id']] = sg

        # Read all etcd keys directly under /calico/policy/profile.
        r = client.read('/calico/policy/profile')
        for child in r.children:
            # Get the bit of the key after the last /.
            profile_id = child.key.rstrip('/').rsplit('/', 1)[-1]
            if profile_id in needed_profiles:
                # This is a profile that we want.  Let's read its rules and
                # tags, and compare those against the current OpenStack data.
                rules = json_decoder.decode(
                    client.read(child.key + '/rules').value)
                tags = json_decoder.decode(
                    client.read(child.key + '/tags').value)

                if (rules == self.profile_rules(profile_id, sgs) and
                    tags == self.profile_tags(profile_id)):
                    # The existing etcd data for this profile is completely
                    # correct.  Delete the profile_id from needed_profiles so
                    # that we don't unnecessarily write out its (unchanged)
                    # data again below.
                    needed_profiles.remove(profile_id)
            else:
                # We don't want this profile any more, so delete the key.
                client.delete(child.key, recursive=True)

        # Now write etcd data for each profile remaining in needed_profiles.
        for profile_id in needed_profiles:
            key = '/calico/policy/profile/' + profile_id
            client.write(key + '/rules', self.profile_rules(profile_id, sgs))
            client.write(key + '/tags', self.profile_tags(profile_id))

    def profile_rules(self, profile_id, sgs):
        inbound = []
        outbound = []
        for sgid in self.profile_tags(profile_id):
            for rule in sgs[sgid]['security_group_rules']:
                LOG.info("Neutron rule %s" % rule)

                ethertype = rule['ethertype']
                etcd_rule = {}

                # Map the protocol field from Neutron to etcd format.
                if rule['protocol'] is None:
                    raise UnsupportedError('protocol None')
                elif rule['protocol'] == 'icmp':
                    etcd_rule['protocol'] = {'IPv4': 'icmp',
                                             'IPv6': 'icmpv6'}[ethertype]
                    etcd_rule['icmp_type'] = rule['port_range_min']
                else:
                    etcd_rule['protocol'] = rule['protocol']

                # OpenStack (sometimes) represents 'any IP address' by setting
                # both 'remote_group_id' and 'remote_ip_prefix' to None.  We
                # translate that to an explicit 0.0.0.0/0 (for IPv4) or ::/0
                # (for IPv6).
                net = rule['remote_ip_prefix']
                if not (net or rule['remote_group_id']):
                    net = {'IPv4': '0.0.0.0/0',
                           'IPv6': '::/0'}[ethertype]

                # src/dst_ports is a list in which each entry can be a single
                # number, or a string describing a port range.
                if rule['port_range_min'] == -1:
                    port_spec = '1:65535'
                elif rule['port_range_min'] == rule['port_range_max']:
                    port_spec = rule['port_range_min']
                else:
                    port_spec = '%s:%s' % (rule['port_range_min'],
                                           rule['port_range_max'])

                # Put it all together and add to either the inbound or the
                # outbound list.
                if rule['direction'] == 'ingress':
                    etcd_rule['src_tag'] = rule['remote_group_id']
                    etcd_rule['src_net'] = net
                    etcd_rule['src_ports'] = [port_spec]
                    inbound.append(etcd_rule)
                    LOG.info("=> Inbound Calico rule %s" % etcd_rule)
                else:
                    etcd_rule['dst_tag'] = rule['remote_group_id']
                    etcd_rule['dst_net'] = net
                    etcd_rule['dst_ports'] = [port_spec]
                    outbound.append(etcd_rule)
                    LOG.info("=> Outbound Calico rule %s" % etcd_rule)

        return {'inbound_rules': inbound, 'outbound_rules': outbound}

    def profile_tags(self, profile_id):
        return profile_id.split('_')

    def endpoint_created(self, port):
        pass

    def endpoint_updated(self, port):
        pass

    def endpoint_deleted(self, port):
        pass

    def security_group_updated(self, sg):
        pass
