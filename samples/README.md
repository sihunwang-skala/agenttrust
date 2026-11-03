# Receipt samples (synthetic)

`sample_export.json` was produced by `backend/scripts/generate_sample.py` with throwaway keys that were deleted afterwards; only the public keys are kept here.
All data is synthetic and the merchant is simulated.

```bash
python verifier/agenttrust_verify.py samples/sample_export.json \
  --public-key samples/gateway_public_key.hex --merchant-public-key samples/mock_merchant_public_key.hex   # exit 0
python verifier/agenttrust_verify.py samples/tampered_export.json --public-key samples/gateway_public_key.hex   # exit 1 (HASH_MISMATCH)
```
`tampered_export.json` is the same export with `quantity` altered in receipt seq 3.
