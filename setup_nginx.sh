#!/bin/bash
set -e

# Step 1: HTTP-only config so nginx can validate and certbot can get the cert
cat > /etc/nginx/sites-available/anki.aeonneo.com << 'EOF'
server {
    listen 80;
    listen [::]:80;
    server_name anki.aeonneo.com;

    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }

    location / {
        proxy_pass http://127.0.0.1:8103;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }
}
EOF

ln -sf /etc/nginx/sites-available/anki.aeonneo.com /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx

# Step 2: certbot gets the cert AND rewrites the config to add SSL
certbot --nginx -d anki.aeonneo.com

echo "Done! anki.aeonneo.com is live."
