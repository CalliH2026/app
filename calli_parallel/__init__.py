"""Calli's bounded adapter around Francois Amat's H Parallel (vendored in vendor/h_parallel).

The upstream modules read their state directory and credentials when first imported, so every entry point
goes through calli_parallel.loader.upstream(), which sets them first.
"""
