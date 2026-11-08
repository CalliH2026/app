// Microphone -> 16 kHz mono 16-bit PCM chunks of about 100 ms, posted to the page (sent to the local server only).
class PcmWorklet extends AudioWorkletProcessor {
  constructor() {
    super();
    this.ratio = sampleRate / 16000;
    this.acc = 0; this.n = 0; this.pos = 0;
    this.out = new Int16Array(1600); this.len = 0;
    // "flush": post the last partial chunk (the end of the last word), then acknowledge
    this.port.onmessage = (e) => {
      if (e.data !== "flush") return;
      if (this.len) {
        const part = this.out.slice(0, this.len);
        this.port.postMessage(part.buffer, [part.buffer]);
        this.len = 0;
      }
      this.port.postMessage("flushed");
    };
  }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch) return true;
    for (let i = 0; i < ch.length; i++) {
      this.acc += ch[i]; this.n += 1; this.pos += 1;
      if (this.pos >= this.ratio) {
        this.pos -= this.ratio;
        const v = Math.max(-1, Math.min(1, this.acc / this.n));
        this.out[this.len++] = v < 0 ? v * 0x8000 : v * 0x7fff;
        this.acc = 0; this.n = 0;
        if (this.len === this.out.length) {
          this.port.postMessage(this.out.buffer, [this.out.buffer]);
          this.out = new Int16Array(1600); this.len = 0;
        }
      }
    }
    return true;
  }
}
registerProcessor("pcm-worklet", PcmWorklet);
