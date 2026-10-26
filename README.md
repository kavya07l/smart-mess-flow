# Smart Mess Flow and Crowd Management System

A beginner-friendly Flask and SQLite demo for controlling hostel mess entry with
meal slots, day-scholar payments, QR booking passes, staff check-in/out, and
counter queue tracking.

## Run locally

1. Install Python 3.9 or newer.
2. In this folder, run:

   ```powershell
   pip install -r requirements.txt
   python app.py
   ```

3. Open <http://127.0.0.1:5000>.

SQLite data is stored in `mess.db` next to `app.py` and seeded automatically on
first run. Set the `MESS_DATABASE` environment variable to use another database
file. The app uses a random session key for local runs; set a private
`SECRET_KEY` environment variable when deploying so sessions stay valid across
restarts. Debug mode is disabled. This is a classroom/demo application; add
production-grade payment, CSRF, and deployment controls before using it with
real student data.

## Demo accounts

| Role | ID | Password |
| --- | --- | --- |
| Hostel student | `hostel01` | `hostel123` |
| Day scholar | `day01` | `day123` |
| Mess staff | `staff01` | `staff123` |
| Admin | `admin01` | `admin123` |

Students can register with their own ID. A day scholar starts unpaid and must
use the simulated payment button before booking. The demo payment does not
process real money.

The demo credentials above are public by design so reviewers can explore the
sample app. Do not reuse these passwords or enter real student information.

## How it works

- Students choose a meal and requested slot. When that slot is full, the app
  attempts the next later slot for that meal. A student may book each meal once
  per local calendar day.
- Staff enter the booking ID shown on the QR pass and select Entry or Exit.
  Entry is allowed only during the slot's local time window.
- The shortest food-counter queue receives each entering student. Counter
  assignments are kept with bookings so exit decreases the correct queue.
- Dashboard occupancy counts bookings currently in the `entered` state.
  Waiting estimate is `(sum of counter queue lengths / counter count) * 2`
  minutes.
- Seed slots are 30-minute windows, three per meal, with capacity 50 each.

## Project files

```text
app.py
database.py
requirements.txt
templates/
static/
```
