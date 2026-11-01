// Writes tray.png: a 32x32 blue disc with a yellow "C" shape. No dependencies, pure Node (zlib).
// Run once with `npm run icon`; the result is committed so `npm start` needs nothing else.
const zlib = require("zlib");
const fs = require("fs");
const path = require("path");

const SIZE = 32;
const px = Buffer.alloc(SIZE * SIZE * 4);
const BLUE = [0, 100, 224, 255];
const YELLOW = [255, 210, 63, 255];
const c = (SIZE - 1) / 2;
for (let y = 0; y < SIZE; y++) {
  for (let x = 0; x < SIZE; x++) {
    const dx = x - c, dy = y - c;
    const r = Math.sqrt(dx * dx + dy * dy);
    let color = [0, 0, 0, 0];
    if (r <= 15.5) color = BLUE;
    // "C": a ring with a gap on the right side
    if (r >= 6.5 && r <= 10.5) {
      const ang = Math.atan2(dy, dx);
      if (Math.abs(ang) > 0.75) color = YELLOW;
    }
    px.set(color, (y * SIZE + x) * 4);
  }
}
// PNG: filter byte 0 at the start of each row
const raw = Buffer.alloc((SIZE * 4 + 1) * SIZE);
for (let y = 0; y < SIZE; y++) {
  raw[y * (SIZE * 4 + 1)] = 0;
  px.copy(raw, y * (SIZE * 4 + 1) + 1, y * SIZE * 4, (y + 1) * SIZE * 4);
}
const crcTable = [];
for (let n = 0; n < 256; n++) { let cc = n; for (let k = 0; k < 8; k++) cc = cc & 1 ? 0xedb88320 ^ (cc >>> 1) : cc >>> 1; crcTable[n] = cc >>> 0; }
function crc32(buf) { let cc = 0xffffffff; for (const b of buf) cc = crcTable[(cc ^ b) & 0xff] ^ (cc >>> 8); return (cc ^ 0xffffffff) >>> 0; }
function chunk(type, data) {
  const len = Buffer.alloc(4); len.writeUInt32BE(data.length);
  const td = Buffer.concat([Buffer.from(type, "ascii"), data]);
  const crc = Buffer.alloc(4); crc.writeUInt32BE(crc32(td));
  return Buffer.concat([len, td, crc]);
}
const ihdr = Buffer.alloc(13);
ihdr.writeUInt32BE(SIZE, 0); ihdr.writeUInt32BE(SIZE, 4);
ihdr[8] = 8; ihdr[9] = 6; ihdr[10] = 0; ihdr[11] = 0; ihdr[12] = 0;
const png = Buffer.concat([
  Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
  chunk("IHDR", ihdr),
  chunk("IDAT", zlib.deflateSync(raw)),
  chunk("IEND", Buffer.alloc(0)),
]);
const out = path.join(__dirname, "tray.png");
fs.writeFileSync(out, png);
console.log("wrote", out, png.length, "bytes");
