# Sentinel grid ingest spec

Source: https://sentinel.gujarat.gov.in/resource (Integrator's Guide, read 2026-09-08).
The `<host>` is only shown after login, so it goes in .env when we have it.

The gateway is MediaMTX (ports 8554 RTSP, 8889 WHEP). We run the same locally so
the dev path and the event path are identical.

## Endpoints

    RTSP    rtsp://<host>:8554/stream/<id>          inference
    WHEP    http://<host>:8889/stream/<id>/whep     browser preview
    HLS     http://<host>/live/stream/<id>/index.m3u8

    catalogue: GET http://<host>/api/ingest

Catalogue is the contract, the URL pattern is not. Camera ids change. Never
hard-code a stream list; always resolve from /api/ingest.

## Hard constraints

Real time only. No seeking, no byte ranges, no running ahead. A movement
history can only be built as fast as the footage plays, which means the
pipeline has to be up and capturing continuously during evaluation.

No downloads. `/stream/<id>` answers range requests, so curl or wget yields a
partial file that looks complete. Anything built against a local copy will
break on the day.

Consume only. Do not publish to the gateway, do not touch its control API.

Each client gets its own copy of the stream, so open only what we are actively
processing and close captures when done. This is why the scheduler exists.

## Things that will break a naive pipeline

These are lifted from their guide because they read like a list of the bugs
they intend to see.

1. RTSP over TCP, everywhere. UDP is accepted but corrupts frames across NAT
   and looks exactly like a model bug. If 8554 is blocked, fall back to HLS.

2. Declared frame rate is wrong. CAP_PROP_FPS does not match delivery. Any
   speed, dwell time or distance derived from it is garbage. Ignore it.

3. All timing from PTS, never arrival time. On connect the gateway replays its
   buffered GOP so the decoder can start on a keyframe, so the first second or
   two arrives faster than real time. A tracker timestamping on arrival will
   compute impossible velocities after every single reconnect. Kalman and
   ByteTrack both need PTS deltas fed in.

4. Frame intervals are not uniform. A gap is not a disconnect.

5. Reconnect with exponential backoff, 2s start, 30s cap. Feeds are supervised
   and restart. No tight loops.

6. Decoder errors on join are normal. "Error constructing the frame RPS" and
   "Could not find ref with POC" appear until the first IDR. Log them, never
   abort on them.

7. Mixed everything. H.264 and H.265, different resolutions, frame rates and
   bitrates per camera. Read per-camera properties from the catalogue. A
   fixed-shape inference batch across all cameras will not work.

8. Feeds loop. At the loop point the scene cuts hard, like a camera reboot.
   Background models, ReID galleries and track ids must recover from that
   rather than assuming continuity. Note this also means a vehicle can
   legitimately appear more than once in a trace.

## Conformance checklist

Their section 4, which we should be able to tick honestly before submitting.

- [ ] every client forces RTSP over TCP
- [ ] no timing logic uses CAP_PROP_FPS or arrival time
- [ ] inter-frame gaps do not stall or crash the pipeline
- [ ] reconnect with backoff, tested by actually restarting a feed
- [ ] decoder warnings on join logged, not fatal
- [ ] camera list and properties read from /api/ingest
- [ ] mixed H.264/H.265 and mixed resolutions handled
- [ ] behaviour sane across a scene discontinuity
