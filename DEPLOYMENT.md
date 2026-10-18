# Public deployment notes

The local URL `http://127.0.0.1:5000` is only accessible from the computer running the app. It is not a shareable public URL.

Before deployment:
1. Replace sample data and get instructor approval.
2. Add authentication/authorization for reset and simulation controls.
3. Replace the local JSON state store with a persistent database and add locking/transactions for concurrent use.
4. Set a strong `SECRET_KEY` environment variable.
5. Configure persistent storage for state, audit logs, and reports.
6. Choose a Python-capable hosting service, deploy the repository, and test the public URL from another device.
7. Do not publish student personal data or private seller information.
8. Confirm whether the course requires a specific hosting provider.

A generic start command for a WSGI server can be configured after selecting a host; this prototype intentionally does not claim to be deployed or publicly reachable.
