"""Local HTTP API and static manager UI for Word Session.

Call ``start_server(service)`` to serve the API on a random localhost port and
``create_app(...)`` to build the ASGI application for tests. Only this package
imports FastAPI, Starlette and uvicorn.
"""
