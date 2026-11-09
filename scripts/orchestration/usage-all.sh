#!/bin/sh
# Token + cost table for every session in the build so far (reads opencode session export).
cd "$(dirname "$0")/../.." && exec python3 scripts/orchestration/usage.py \
  orchestrator=ses_e5e0e07a8ffeNS2flouzfA6Z4q orchestrator2=ses_e5cfd3c23ffee1W6h4E7UXcj50 \
  orchestrator3=ses_e59e0b9f7ffe3ms3p7CJIoJNj6 \
  G0b=ses_e5df3df8bffesGopzuwCdJWAc9 \
  S1=ses_e5d119adaffeI1bNZrPkyG4Xm4 S2=ses_e5d11ac66ffe7gw7ikccXYNEcE \
  S3=ses_e5d11a3abffewYln3h9GsjLWUm S4=ses_e5d118626ffecY714tAqZS17cz \
  S5=ses_e5d11644cffeeo53sKWmE6JdKw S6=ses_e5d114a9effeA8A3C7yDLNR9rh \
  C1=ses_e5d1140f8ffeMXb75kryKwGzze S1fix=ses_e5c9a4de1fferKp1BzSfF2KVDC \
  S2fix=ses_e5a490336ffecftBR5g4NZI8fs S1retry=ses_e5a48fb4affecMnryQLtTr4Egz \
  I1=ses_e59d83e96ffeXh1qvsGqSNtO4w I2=ses_e59d8373dffeVAKzZu66T80EVW I3=ses_e59d8300fffe7KwXIn6264yS44 \
  R1=ses_e59bb584cffeJmkoiUxp9U7wkk A1=ses_e59197cfdffeFmlFIijLespmkE \
  tests=ses_e5e0d091cffenJE471FxGQT7X6 tests2=ses_e5e08329bffebSdIOd3qH6JYpb
