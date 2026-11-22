# Run behind a reverse proxy

For use beyond one machine, put a TLS-terminating proxy in front of the container and keep the
container's port on the loopback or a private network (`OPENARTIFACT_BIND=127.0.0.1`, the default).
The application checks several things that a proxy can break; this guide lists what it must do.

## Requirements on the proxy

| Requirement | Why |
|-------------|-----|
| **Pass the original `Host` header** (nginx: `proxy_set_header Host $host;`) | The cross-site guard compares the browser's `Origin` with `Host` on every unsafe request; with a rewritten `Host` every write from the browser fails with `403`. `OPENARTIFACT_ALLOWED_HOSTS` is checked against it too. |
| **Send `X-Forwarded-Proto`** and set `FORWARDED_ALLOW_IPS` | uvicorn trusts forwarded headers only from the addresses in `FORWARDED_ALLOW_IPS` (default `127.0.0.1`). From another container the application would see `http` and issue the session cookie without `Secure`. |
| **Do not buffer the event stream** | `GET /api/events` is a server-sent event stream; buffering delays live updates. |
| **Allow request bodies of at least 1 MiB** | The application's own cap is `OPENARTIFACT_MAX_REQUEST_BYTES` (default 1 MiB, `413`). nginx's default `client_max_body_size` is also 1 MiB; set it to match. |
| **Do not remove security headers** | The application sends CSP, `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy` and, over HTTPS, `Strict-Transport-Security`. |
| **Terminate TLS** | The cookie is only `Secure` over HTTPS, and the token travels in clear text otherwise. |

## Settings in `deploy/.env`

```ini
OPENARTIFACT_API_TOKEN=<openssl rand -hex 32>
OPENARTIFACT_SECRET_KEY=<another openssl rand -hex 32>
OPENARTIFACT_ALLOWED_HOSTS=oa.example.com
OPENARTIFACT_COOKIE_SECURE=true
FORWARDED_ALLOW_IPS=<address the proxy connects from>
```

`OPENARTIFACT_COOKIE_SECURE=true` makes the cookie `Secure` (name `__Host-oa_session`) whatever the proxy
tells uvicorn, and the application then also sends `Strict-Transport-Security: max-age=31536000`. With
`auto` the cookie follows the request scheme, which needs `FORWARDED_ALLOW_IPS` to be right. Use `true`
when the proxy is the only way in: it is the safer of the two. `/health` stays reachable under any `Host`
header, so the container's health check keeps working with `ALLOWED_HOSTS` set.

For a proxy on the same host, the container is published on `127.0.0.1:2909`; the proxy's address as seen
by the container is the Docker bridge gateway (`docker network inspect deploy_default` shows it), or
`*` if nothing but the proxy can reach the port.

## nginx

```nginx
server {
    listen 443 ssl;
    server_name oa.example.com;
    # ssl_certificate / ssl_certificate_key ...

    client_max_body_size 1m;

    location / {
        proxy_pass http://127.0.0.1:2909;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Connection "";
        proxy_buffering off;        # keeps /api/events live
        proxy_read_timeout 1h;
    }
}
```

HSTS comes from the application whenever the request is https (always with `OPENARTIFACT_COOKIE_SECURE=true`); do not add a second header.

## Caddy

```caddyfile
oa.example.com {
    reverse_proxy 127.0.0.1:2909 {
        flush_interval -1      # keeps /api/events live
    }
}
```

Caddy keeps the `Host` header and sends `X-Forwarded-Proto` and `X-Forwarded-For`, and obtains the
certificate itself. Its request body limit is unlimited by default; the application's own cap applies.

## Check it

```bash
curl -sI https://oa.example.com/health                    # 200, any host
curl -sI https://oa.example.com/                          # 303 to /login (token set)
curl -sI -H 'Host: other.example' http://127.0.0.1:2909/  # 400 Invalid host header (ALLOWED_HOSTS set)
```

After signing in, the browser's cookie list shows `__Host-oa_session` with `Secure` and `HttpOnly`.

## What is not covered

There is no rate limiting in the application beyond a half-second delay on a wrong token; add it at the
proxy if the instance is reachable from the internet. The application is built for one process: do not
run several containers against the same volume (see the risks in arc42 chapter 11).
