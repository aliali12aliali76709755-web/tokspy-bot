"""
High-Performance DNS Accelerator & In-Memory Resolver Cache.
Bypasses Docker container internal DNS timeouts (127.0.0.11) by:
1. Configuring dnspython with public ultra-fast DNS (8.8.8.8, 1.1.1.1, 8.8.4.4, 1.0.0.1).
2. Monkey-patching socket.getaddrinfo with an in-memory TTL cache and direct public DNS resolution.
"""
import socket
import threading
import time
import dns.resolver

# 1. Direct Public Resolver for PyMongo/Motor SRV lookups and domain resolution
_resolver = dns.resolver.Resolver(configure=False)
_resolver.nameservers = ['8.8.8.8', '1.1.1.1', '8.8.4.4', '1.0.0.1']
_resolver.timeout = 2.0
_resolver.lifetime = 3.5
dns.resolver.default_resolver = _resolver

# 2. In-memory Thread-Safe DNS Cache for socket.getaddrinfo
_DNS_CACHE = {}
_DNS_LOCK = threading.Lock()
_ORIG_GETADDRINFO = socket.getaddrinfo

# Pre-cached popular hostnames for instant zero-latency lookup
_STATIC_IPS = {
    'api.telegram.org': '149.154.166.110',
}

def _resolve_a(hostname: str) -> str | None:
    try:
        answers = _resolver.resolve(hostname, 'A')
        for r in answers:
            return r.to_text()
    except Exception:
        pass
    return None

def _accelerated_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    if isinstance(host, bytes):
        try:
            host_str = host.decode('idna')
        except Exception:
            host_str = str(host)
    else:
        host_str = str(host) if host is not None else ''

    # If host is empty, numeric IP, IPv6, or localhost, forward directly
    if not host_str or host_str.replace('.', '').isdigit() or ':' in host_str or host_str in ('localhost', '127.0.0.1'):
        return _ORIG_GETADDRINFO(host, port, family, type, proto, flags)

    h_lower = host_str.lower()
    cache_key = (h_lower, port, family, type, proto, flags)
    now = time.time()

    with _DNS_LOCK:
        if cache_key in _DNS_CACHE:
            ts, res = _DNS_CACHE[cache_key]
            if now - ts < 1800:  # 30 min TTL
                return res

    # Resolve via direct Google/Cloudflare DNS
    ip = _STATIC_IPS.get(h_lower) or _resolve_a(h_lower)
    if ip:
        try:
            res = _ORIG_GETADDRINFO(ip, port, family, type, proto, flags)
            with _DNS_LOCK:
                _DNS_CACHE[cache_key] = (now, res)
            return res
        except Exception:
            pass

    # Fallback to system resolver
    res = _ORIG_GETADDRINFO(host, port, family, type, proto, flags)
    with _DNS_LOCK:
        _DNS_CACHE[cache_key] = (now, res)
    return res

socket.getaddrinfo = _accelerated_getaddrinfo
