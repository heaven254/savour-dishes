# Savour Dishes – Python backend

Flask + SQLite. The same server also serves the website, so there is nothing else to run.

## Run it

```
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000

By default it keeps everything in one SQLite file (`saviour.db`), which is fine for trying it out. For real use, switch to PostgreSQL: see **PostgreSQL** below.

## Folder layout

```
saviour-backend/
  app.py            the API + database (creates saviour.db on first run)
  requirements.txt
  docker-compose.yml   a ready-made PostgreSQL database (optional)
  postgres-schema.sql  reference copy of the tables (the app creates them itself)
  static/index.html the website (customer + staff/owner login)
  static/img/       logo and dish photos
```

## Staff dashboard layout

After logging in, staff and the owner land on a **home screen** like a mobile-money app: a card with today's sales, open orders and
payments not yet confirmed, then a grid of icon tiles for every section they may open. Red numbers on the **Orders** and
**Transactions** tiles show what needs attention. Tapping a tile opens that section; the **←** button (or the phone's back button)
returns home. Sections the owner has switched off simply don't appear.

## Owner and staff

- **Owner** (`staff01` on first run) can open everything and has an extra **Access** tab.
- **Staff** can open everything too, until the owner switches sections off for them.

Set the owner's password before the first run:

```
SD_ADMIN_PASSWORD="choose-a-strong-one" python app.py
```

If you don't, the password is `saviour123`; change it before going live.

In the **Access** tab the owner can add a staff member and tick or untick each section
(Overview, Orders, Sales, Purchases, Expenses, Transactions, Staff report, Menu, Customers) for that person.
Changes apply straight away, even if the staff member is signed in.

From the command line instead: `python app.py create-staff jane "Jane Doe" Staff`

Older databases are upgraded automatically (Manager becomes Owner; other roles become Staff).

## API

| Method | Path | Who |
|---|---|---|
| POST | /api/register `{phone, name?, location?}` | anyone (phone number only) |
| POST | /api/login/customer `{phone}`, /api/login/staff `{id, password}` | anyone |
| PUT, DELETE | /api/me/location | customer (optional location on her account) |
| POST | /api/logout, GET /api/me | logged in |
| GET | /api/menu | anyone |
| PATCH | /api/menu/<id> `{available: bool}` and/or `{price: int}` | *menu* access to switch on/off, *sales* access to change a price |
| GET | /api/price-changes | *sales* access |
| POST, PUT, DELETE | /api/combos, /api/combos/<id> | *sales* access |
| POST | /api/orders `{items, service, location, total?, geo?, payment?}` | customer (`geo` optional; `payment` is `{method: "KCB Till"\|"Cash", reference?}`, cash if left out) |
| GET | /api/orders/mine | customer |
| GET | /api/orders | *orders* access |
| PATCH | /api/orders/<SD0001> `{status}` | *orders* access (Pending → Preparing → Served) |
| GET | /api/payment-info | anyone (payment methods and the till number) |
| PUT | /api/settings/till `{till}` | owner only |
| POST | /api/orders/<SD0001>/payment-ref `{reference}` | customer (adds the M-Pesa code later) |
| GET | /api/transactions?limit=&offset=&method=&status=&from=&to=&q= | *transactions* access (default: last 20) |
| PATCH | /api/transactions/<TX0001> `{status: Paid\|Failed}` | *transactions* access |
| POST | /api/orders/<SD0001>/stk-push `{phone?}` | customer (sends the M-Pesa prompt) |
| GET | /api/mpesa/status | owner only |
| POST | /api/pay/stk/<secret>, /api/pay/c2b/<secret>/confirmation, /validation | Safaricom only (secret is in the address) |
| GET | /api/customers | *customers* access |
| GET | /api/reports/overview?range= | *overview* access |
| GET | /api/sales?range= | *sales* access |
| GET, POST, DELETE | /api/purchases | *purchases* access |
| GET, POST, DELETE | /api/expenses | *expenses* access |
| GET | /api/reports/staff?range= | *team* access |
| GET, PUT | /api/access, /api/access/<staff_id> `{area, allowed}` | owner only |
| POST | /api/staff `{id, name, password}` | owner only |

`range` is one of `today`, `week`, `month` (default) or `all`.
Each order records which staff member started it and which one served it.
Dates use East Africa Time by default; change with `SD_TZ_HOURS` (e.g. `SD_TZ_HOURS=2`).

## Notes

- Passwords are hashed; login tokens are stored hashed and expire after 12 hours.
- Order prices and availability are always taken from the database, never from the browser.
- To let customers on other devices use it, run with `SD_HOST=0.0.0.0` and put it behind HTTPS
  (e.g. nginx or a host like Render/Railway) before using real customer data.

## Menu, photos and logo

The menu (35 dishes, copied from the board on the wall) is in `SEED_MENU` in `app.py`.
It is loaded into the database the first time the app runs; an older sample menu is replaced automatically.

- **Logo:** `static/img/logo.png`. Replace the file with a cleaner copy any time (a clear, straight-on image works best).
- **Dish photos:** a dish shows a round photo if it is listed in `DISH_PHOTOS` in `app.py`; otherwise an emoji avatar.
  Add a photo by copying the file into `static/img/` and adding `"Dish name": "file.jpg"`, then restart. No database change needed.

## Prices and combos

In the **Sales** tab there are three views: Sales log, Item prices and Combos.

- **Item prices:** change any dish's price. It applies to new orders straight away; orders already placed keep the price they were made at.
  Every change is logged (who, when, old and new price). If a price changes while a customer is checking out, they are asked to review their total.
- **Combos:** bundle dishes at one price (for example Chapati x2 + African Tea). Combos show first on the customer menu with the saving.
  A combo is unavailable while any dish in it is switched off. The kitchen sees what is inside each combo on the order.
- The owner controls this with the **Sales** access box in the Access tab.

## Customer sign-in and location

- **Phone number only.** Customers sign up and log in with just their phone number (name is optional).
  Numbers are stored in one standard form, so `0712 345 678`, `712345678` and `+254712345678` are the same customer.
  Staff still use an ID and password.
- **Location is optional and always the customer's choice.** She can share it when signing up, from **My Account**,
  or with a single order at checkout. It is never taken automatically.
  Staff see an "Open map" link next to the customer on each order (and in the Customers tab).
  The order's own location is shown if she shared one, otherwise the one saved on her account.
  The coordinates are never sent back to customers' browsers, and she can remove a saved location any time.
- Browsers only allow location sharing on `https://` addresses or `localhost`, so put the site behind HTTPS when you go live.
- Older databases are upgraded automatically: emails and passwords are dropped and phone numbers are standardised.
- **Trade-off to know about:** anyone who knows a customer's phone number can log in as her and see her order history.
  If that matters, the usual next step is a one-time code sent by SMS (needs an SMS service) or a short PIN.

## Payments and transactions

- **At checkout** the customer chooses **Cash** or **KCB Till (M-Pesa)**. For the till she is shown your till number
  and can type the M-Pesa confirmation code from her payment message, now or later from **My Orders**.
- **The owner sets the till number** in the **Transactions** tab (or start the app with `SD_KCB_TILL=123456`).
- **Without the automatic setup below** the app cannot see M-Pesa, so it cannot confirm that money arrived by itself.
  A staff member or the owner checks the payment (cash in hand, or the code in the till's SMS / KCB statement)
  and presses **Received**. Until then the payment shows as "Not confirmed". **Not received** marks a payment that never came.
  A confirmed payment can't be changed afterwards, and it records who confirmed it and when.
  An M-Pesa code can only be used for one payment.
- **Transactions tab** (staff and owner; the owner can switch it off for staff in Access): the last 20 transactions first,
  totals confirmed by method, and **Show more** to page back through the whole history.
  Filter by method, status, dates, or search by name, phone, order number or M-Pesa code.
- Orders placed before this update have no payment record and don't appear in Transactions.

## Automatic M-Pesa confirmation (optional)

It is **off until you set it up**; until then staff confirm by hand and nothing else changes.

When it is on:
1. After a customer places a till order, a **payment prompt** pops up on her phone (her account number, or another number she types under **Pay now**).
2. When she enters her PIN, Safaricom tells the app, and the payment turns **Paid** by itself, marked "confirmed automatically".
3. If she paid the till by hand instead, Safaricom's till notification plus the M-Pesa code she types confirms it the same way, whichever arrives first.
4. If she cancels, the wrong PIN is used, or she pays too little, the payment stays "Not confirmed" with the reason, and staff decide.
   An underpayment is never confirmed automatically.

**Set-up (uses Safaricom's Daraja service):**
1. Register at developer.safaricom.co.ke, create an app, and get the consumer key and secret. Test in the sandbox first.
2. Your site needs a public **https** address (Safaricom can't reach localhost).
3. Start the app with:

```
SD_MPESA_ENV=sandbox            # change to production when you go live
SD_MPESA_KEY=...  SD_MPESA_SECRET=...
SD_MPESA_SHORTCODE=...          # the shortcode/store number the prompts are sent from, and the passkey for it
SD_MPESA_PASSKEY=...
SD_MPESA_TILL=...               # your till number, if different from the shortcode
SD_PUBLIC_URL=https://your-site.example
python app.py
```

4. For till notifications (step 3 above), run `python app.py mpesa-register` once. The owner's **Transactions** tab also shows the two addresses Safaricom should use.
   Paybill instead of a Buy Goods till: add `SD_MPESA_TYPE=paybill`.

**Check before relying on it:** this was tested here against simulated Safaricom replies, not the live service.
Whether a till issued through KCB can be used with Daraja, and which shortcode and passkey to use for it, is for Safaricom or KCB to confirm.
Run a small real payment in the sandbox and then in production before you stop checking by hand.
The callbacks are protected only by the secret in their address (Safaricom doesn't sign them), so keep the addresses private.
A customer who types someone else's unused M-Pesa code for the same amount could be confirmed by mistake. That is why the prompt, which is tied to her own phone, is the safer route.

## PostgreSQL

Set `DATABASE_URL` and the app uses PostgreSQL instead of the SQLite file. Nothing else changes: it creates its own tables on first start
and upgrades them on later starts. Without `DATABASE_URL` it keeps using SQLite.

1. **Get a database.** Either use a hosted one (Render, Railway, Supabase, Neon... any gives you a connection address), or run one yourself:
   `SD_DB_PASSWORD=choose-a-strong-one docker compose up -d` (uses `docker-compose.yml`).
2. **Install and run:**

```
pip install -r requirements.txt
DATABASE_URL="postgresql://savour:YOUR-PASSWORD@127.0.0.1:5432/savour" SD_ADMIN_PASSWORD="choose-a-strong-one" python app.py
```

   Hosted databases often need `?sslmode=require` at the end of the address. `postgres://` addresses work too.
3. **Keep your existing data** (only if you have been using the SQLite file): start the app once on the old file with this latest version so it is upgraded,
   then, with `DATABASE_URL` set and an empty PostgreSQL database:

```
python app.py migrate-to-postgres saviour.db
```

   It copies staff, customers, menu, combos, orders, payments, purchases, expenses, price history and access settings, and refuses to run
   if the PostgreSQL database already holds customers or orders. Everyone has to log in again afterwards.
4. **Back up** with `pg_dump "$DATABASE_URL" > backup.sql` (most hosts also do this for you).

`SD_DB_POOL` (default 10) sets how many database connections the app keeps. For a live site, run it with a production server instead of `python app.py`:
`gunicorn app:app --workers 1 --threads 8 --bind 0.0.0.0:$PORT` (one worker on purpose: the app keeps a few short-lived counters in memory and sets up the tables on start).

## Deploying on Render

1. Put the project on GitHub. Create a **PostgreSQL** database on Render, then a **Web Service** from the repo.
2. Web Service settings: **Build command** `pip install -r requirements.txt`; **Start command** `gunicorn app:app --workers 1 --threads 8 --bind 0.0.0.0:$PORT`.
3. Under **Environment**, add:

| Name | Value |
|---|---|
| `DATABASE_URL` | the database's **Internal Database URL** (same region as the web service) |
| `SD_ADMIN_PASSWORD` | a strong owner password (used the first time only) |
| `SD_KCB_TILL` | your till number (optional; the owner can also set it in the app) |

   For automatic M-Pesa add `SD_PUBLIC_URL` (your Render address, `https://your-app.onrender.com`) and the `SD_MPESA_*` values listed above.
4. Don't set `SD_HOST` or `SD_PORT` (Render gives the port). Render serves the site over HTTPS, which customers' location sharing needs.
5. Render's disk is wiped on every deploy, so keep everything in PostgreSQL, not the SQLite file. Check your database plan's expiry and backups on Render.
