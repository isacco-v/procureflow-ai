"""Provider boundary.

The mock completion provider and the investigation test double do not open a
network connection. The OpenAI investigation adapter is installed and stays
inactive unless the server-side live gate is open.
"""
