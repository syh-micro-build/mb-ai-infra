proxy_http_version 1.1;
proxy_set_header Host $host;
proxy_set_header X-Real-IP $remote_addr;
# The Edge is the public boundary. Discard spoofed forwarding headers.
proxy_set_header X-Forwarded-For $remote_addr;
proxy_set_header X-Forwarded-Proto $scheme;
proxy_set_header Upgrade $http_upgrade;
proxy_set_header Connection $connection_upgrade;
proxy_connect_timeout 10s;
proxy_read_timeout 3600s;
proxy_send_timeout 3600s;
proxy_next_upstream off;
proxy_cache off;
