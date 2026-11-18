#!/usr/bin/env bash
# Prove the demo HA container has no network path out. Every probe below must FAIL to connect.
set -uo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
HA="${COMPOSE_PROJECT_NAME}-ha-1"
LAN_IP="$(ip -4 route get 1.1.1.1 | sed -n 's/.* src \([0-9.]*\).*/\1/p')"
BR_GW="$(docker network inspect bridge -f '{{(index .IPAM.Config 0).Gateway}}')"
probe() { # label host port
  if docker exec "$HA" python3 -c "
import socket,sys
s=socket.socket(); s.settimeout(4)
try: s.connect(('$2',$3)); print('CONNECTED')
except Exception as e: print('blocked:',type(e).__name__)" | grep -q CONNECTED; then echo "FAIL   $1 :$3 reachable"; BAD=1; else echo "ok     $1 :$3 blocked"; fi
}
BAD=0
# Positive control: the probe itself must be able to connect when a path exists (HA's own port, in-container).
docker exec "$HA" python3 -c "
import socket; s=socket.socket(); s.settimeout(4); s.connect(('127.0.0.1',8123)); print('ok     control: in-container 127.0.0.1:8123 connects (probe works)')" || BAD=1
probe "libvirt gateway" 192.168.122.1 22; probe "libvirt gateway" 192.168.122.1 8123
probe "host LAN address" "$LAN_IP" 1883; probe "host LAN address" "$LAN_IP" 8123
probe "default bridge gateway" "$BR_GW" 1883; probe "default bridge gateway" "$BR_GW" 8123
probe "host.docker.internal" host.docker.internal 1883; probe "host.docker.internal" host.docker.internal 8123
probe "internet (1.1.1.1)" 1.1.1.1 443
docker exec "$HA" python3 -c "
import socket
try: print('dns resolved', socket.gethostbyname('example.com'))
except Exception as e: print('ok     DNS example.com blocked:', type(e).__name__)"
echo "container networks: $(docker inspect "$HA" -f '{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}')"
echo "network internal flag: $(docker network inspect "${COMPOSE_PROJECT_NAME}_demo_internal" -f '{{.Internal}}')"
docker inspect "$HA" -f 'privileged={{.HostConfig.Privileged}} netmode={{.HostConfig.NetworkMode}} devices={{len .HostConfig.Devices}}'
exit $BAD
