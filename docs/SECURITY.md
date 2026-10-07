# Bezpečnost

server-meter je monitorovací služba na lokální síti. **Není** to produkt pro zveřejnění na internet bez TLS a dalšího zpevnění.

> HTTP Basic Authentication přes nešifrované HTTP neposkytuje šifrování hesla.

Pro důvěryhodnou izolovanou LAN může být čisté HTTP přijatelné podle vašeho provozního modelu.

Pro nedůvěryhodnou síť nebo vzdálený přístup z internetu použijte **HTTPS** (reverse proxy). Aplikace sama TLS neukončuje.

---

## HTTP Basic Auth

| Položka | Implementace |
|---|---|
| Typ | RFC 7617 Basic (`Authorization: Basic …`) |
| Kód | `server_meter/api/auth.py` |
| Porovnání | `hmac.compare_digest` na username i password |
| Úložiště hesla | **pouze YAML**, plaintext |
| Hash v YAML | **neexistuje** |
| Logování hesla | kód heslo neloguje a nevrací v `/api/status` |

Ve výchozím YAML:

```yaml
web:
  auth:
    enabled: true
    username: "admin"
    password: "YOUR_PASSWORD"
```

V `environment: production`:

- `auth.enabled` musí být `true`
- username nesmí být prázdný
- password nesmí být prázdné, minimálně **8 znaků**
- `CHANGE_ME` je tovární heslo; po instalaci ho změňte a proveďte `sudo systemctl restart server-meter`

Heslo **není** ve zdrojovém kódu. `CHANGE_ME` v `config.example.yaml` je výchozí hodnota, kterou UI označí jako aktivní tovární heslo.

Prohlížeč i `curl -u` posílají údaje v každém požadavku. Na Wi-Fi kavárny nebo internet to bez TLS nepoužívejte.

---

## Oprávnění YAML

`install.sh` nastaví:

```text
/etc/server-meter               mode 750   root:server-meter
/etc/server-meter/config.yaml   mode 640   root:server-meter
```

750 na adresáři = root a skupina `server-meter` smí adresář projít. 640 na YAML = root čte/píše, skupina `server-meter` čte, ostatní nic.

Samotné 640 na souboru **nestačí**: když je `/etc/server-meter` `root:root` 0750, uživatel `server-meter` soubor „nevidí“ (`Path.is_file()` vrátí false → `Configuration file not found`).

### Ověř

```bash
stat -c '%a %U %G' /etc/server-meter /etc/server-meter/config.yaml
sudo -u server-meter test -r /etc/server-meter/config.yaml && echo readable
```

Očekávaný výsledek: `750 root server-meter` a `640 root server-meter`, plus `readable`.

Úprava:

```bash
sudo chown root:server-meter /etc/server-meter
sudo chmod 0750 /etc/server-meter
sudo chmod 640 /etc/server-meter/config.yaml
sudo chown root:server-meter /etc/server-meter/config.yaml
```

Nepoužívejte `chmod 777` ani `chmod 644` na soubor s heslem.

Aplikace YAML **nikdy zpět nezapisuje**.

---

## Uživatel služby

Proces **neběží jako root**.

```text
User=server-meter
Group=server-meter
SupplementaryGroups=i2c
```

Systémový účet z `install.sh`:

```bash
adduser --system --group --home /opt/server-meter --no-create-home --shell /usr/sbin/nologin server-meter
```

### Ověř

```bash
id server-meter
groups server-meter
```

Očekávejte skupiny `server-meter` a `i2c` (pokud skupina `i2c` na systému existuje).

Pokud `i2c` chybí, `enable_i2c.sh` ji založí; `install.sh` volá `usermod -aG i2c` jen když skupina už existuje (`|| true` při chybě). Po instalaci ověřte a případně:

```bash
sudo usermod -aG i2c server-meter
```

Nová skupina se projeví až v **nové** relaci procesu:

```bash
sudo systemctl restart server-meter
```

---

## I²C oprávnění

Zařízení `/dev/i2c-1` bývá `root:i2c` režim `660` (závisí na udev).

Uživatel v `i2c` smí bus používat bez root.

Unit navíc:

```text
DevicePolicy=closed
DeviceAllow=/dev/i2c-0 rw
DeviceAllow=/dev/i2c-1 rw
DeviceAllow=/dev/i2c-2 rw
```

Ostatní device uzly proces neotevře.

Test:

```bash
sudo -u server-meter i2cdetect -y 1
```

`Permission denied` → skupina nebo DeviceAllow. Viz [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

---

## systemd hardening (skutečné direktivy)

Z `systemd/server-meter.service`:

- `NoNewPrivileges=true`
- `PrivateTmp=true`
- `ProtectSystem=strict`
- `ProtectHome=true`
- `ProtectKernelModules=true`
- `ProtectControlGroups=true`
- `ProtectHostname=true`
- `ProtectClock=true`
- `LockPersonality=true`
- `RestrictSUIDSGID=true`
- `RestrictRealtime=true`
- `RestrictNamespaces=true`
- `RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6`
- `CapabilityBoundingSet=` (prázdné)
- `UMask=0027`
- `ReadOnlyPaths=/opt/server-meter /etc/server-meter`
- prázdné `ReadWritePaths`

`MemoryDenyWriteExecute=false` kvůli načtení BSEC `.so`.

---

## Firewall (UFW)

Ubuntu Server 26.04 může mít UFW nainstalovaný, ale **nemusí** být aktivní.

### 1. Zjistěte stav

```bash
sudo ufw status
```

Pokud `inactive`, UFW provoz nefiltruje. Port 8080 je dostupný podle jiné firewall vrstvy (nebo vůbec).

### 2. Bezpečnější pravidlo (preferované)

Omezte 8080 na IP **Nagios serveru** (`NAGIOS_SERVER_IP` nahraďte):

```bash
sudo ufw allow OpenSSH
sudo ufw allow from NAGIOS_SERVER_IP to any port 8080 proto tcp comment 'server-meter nagios'
sudo ufw enable
sudo ufw status numbered
```

SSH pravidlo přidejte **před** `ufw enable`, ať se neodříznete.

Celá důvěryhodná LAN (příklad `192.168.1.0/24` — **upravte** podle své sítě):

```bash
sudo ufw allow from 192.168.1.0/24 to any port 8080 proto tcp comment 'server-meter lan'
```

### Méně bezpečné (nedoporučeno jako první volba)

```bash
sudo ufw allow 8080/tcp comment 'server-meter (all sources)'
```

To otevře dashboard a API z celého internetu, pokud má Pi veřejnou adresu nebo port forwarding.

### Ověř z Nagios serveru

```bash
curl -u admin:YOUR_PASSWORD http://RPI_IP:8080/api/health
```

Health je ve výchozím stavu bez hesla; zbytek API heslo vyžaduje.

---

## Statické soubory bez hesla

`/css`, `/js`, `/vendor` **nejsou** za Basic Auth (`app.py` mount StaticFiles). Útočník na síti si může stáhnout Chart.js a `app.js`. **Data měření** jdou jen přes autentizované `/api/*` a HTML `/`.

To je známé omezení implementace, ne dokumentační omyl.

---

## Veřejný health endpoint

`web.health_public: true` (výchozí) — `/api/health` bez hesla, bez I²C. Hodí se na liveness.

Chcete-li ho schovat:

```yaml
web:
  health_public: false
```

Pak i health vyžaduje Basic Auth.

---

## OpenAPI

V production `web.api_docs_enabled: true` **zakáže start**. Nenechávejte Swagger na 8080 v produkci.

---

## TLS a reverse proxy

Aplikace naslouchá HTTP. Uvicorn má `proxy_headers=True`.

Doporučený model na nedůvěryhodné síti:

```text
Klient ──HTTPS──► nginx/Caddy (TLS) ──HTTP──► 127.0.0.1:8080
```

V YAML:

```yaml
web:
  host: "127.0.0.1"
  port: 8080
```

Pak 8080 není na LAN. Proxy musí umět předat `Authorization` (Basic Auth zůstane, nebo auth přesunete na proxy — to už tento projekt neřeší).

nginx/Caddy **nejsou** součástí server-meter. Konfiguraci proxy spravujete vy. Příklad nginx (operátorský, ověřte na své verzi):

```nginx
server {
    listen 443 ssl;
    server_name meter.example.lan;
    ssl_certificate     /etc/ssl/certs/meter.crt;
    ssl_certificate_key /etc/ssl/private/meter.key;
    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header Authorization $http_authorization;
        proxy_pass_header WWW-Authenticate;
    }
}
```

Cesty k certifikátům jsou **vaše**. Tento soubor v gitu není.

Firewall pak 8080 zvenku neotevírejte.

---

## Síťový bind

`web.host: "0.0.0.0"` (produkční example) naslouchá na všech rozhraních.

`config.mock.yaml` používá `127.0.0.1` — jen localhost.

---

## Co aplikace nesmí

- spouštět se jako root (unit to nedělá)
- zapisovat historii na disk
- vracet heslo v JSON
- logovat naměřené řady do souboru

Pokud toto uvidíte, nejde o dokumentovanou funkci.
