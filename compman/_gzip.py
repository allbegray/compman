"""Gzip compression level shared by every archive writer.

Lives in its own import-free module so the CLI can read the default without
pulling tarfile/zipfile into its startup path.
"""

DEFAULT_GZIP_LEVEL = 6
