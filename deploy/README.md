# Tablebuilder — Totoro Deployment

## Prerequisites

- Node.js 20+ on Totoro
- nginx: `sudo apt install nginx`
- Playwright Chromium: `npx playwright install chromium --with-deps`
- Port 80 restricted to Cloudflare IPs (see firewall section)

## Deploy steps

### 1. Build locally

```bash
npm run build
```

### 2. Sync to Totoro

Run from `~/code/rmai/tablebuilder/`:

```bash
rsync -avz --exclude node_modules --exclude .env \
  . ubuntu@totoro:/opt/tablebuilder/
ssh ubuntu@totoro "cd /opt/tablebuilder && npm install --production"
```

### 3. Generate COOKIE_SECRET

```bash
openssl rand -hex 32
```

### 4. Create /opt/tablebuilder/.env on Totoro

```
PORT=3000
COOKIE_SECRET=<output from step 3>
NODE_ENV=production
```

### 5. Install and start systemd service

```bash
sudo cp deploy/tablebuilder.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable tablebuilder
sudo systemctl start tablebuilder
sudo systemctl status tablebuilder
```

### 6. Configure nginx

```bash
sudo cp deploy/nginx.conf /etc/nginx/sites-available/tablebuilder
sudo ln -s /etc/nginx/sites-available/tablebuilder /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

### 7. Restrict port 80 to Cloudflare IPs (mandatory)

Prevents direct-to-server requests with forged CF-Connecting-IP headers:

```bash
for cidr in \
  103.21.244.0/22 103.22.200.0/22 103.31.4.0/22 104.16.0.0/13 \
  104.24.0.0/14 108.162.192.0/18 131.0.72.0/22 141.101.64.0/18 \
  162.158.0.0/15 172.64.0.0/13 173.245.48.0/20 188.114.96.0/20 \
  190.93.240.0/20 197.234.240.0/22 198.41.128.0/17; do
  sudo ufw allow from $cidr to any port 80
done
sudo ufw deny 80
```

### 8. Configure Cloudflare

- Domain: `tablebuilder.realmindsai.com.au`
- DNS: A record `tablebuilder` → Totoro public IP, proxied (orange cloud)
- SSL/TLS: Full (strict)

## Checking logs

```bash
tail -f ~/.tablebuilder/logs/$(date +%Y-%m-%d).jsonl | jq .
```

## Service management

```bash
sudo systemctl restart tablebuilder   # after code update
sudo journalctl -u tablebuilder -f    # live logs
```

## Deployment checklist

- [ ] `npm run build` exits 0
- [ ] `npm test` all pass
- [ ] COOKIE_SECRET generated and set in /opt/tablebuilder/.env
- [ ] systemd service running
- [ ] nginx configured and reloaded
- [ ] Port 80 restricted to Cloudflare IPs
- [ ] Cloudflare DNS A record → Totoro IP, proxied
- [ ] https://tablebuilder.realmindsai.com.au loads login page
