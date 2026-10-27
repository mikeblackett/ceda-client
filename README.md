# ceda-client

Python client for the [CEDA Archive](https://data.ceda.ac.uk/).

Why this exists: CEDA serves data over DAP2, and DAP2 has no int64 type.
Standard tools such as `pydap` therefore cannot download datasets that
contain int64 data. This client uses CEDA's JSON listings (a `json`
query parameter on any directory URL) and downloads files directly over
HTTP, sidestepping the DAP2 limitation.

If your data has no int64 (and nothing else specific to this client),
prefer a tool like `pydap`.
