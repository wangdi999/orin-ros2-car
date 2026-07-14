import { createReadStream } from 'node:fs';
import { readdir, stat } from 'node:fs/promises';
import path from 'node:path';

const CRC_TABLE = makeCrcTable();

export async function streamZipDirectory(root, zipName, res) {
  const files = await collectFiles(root);
  const central = [];
  let offset = 0;

  res.writeHead(200, {
    'content-type': 'application/zip',
    'content-disposition': `attachment; filename="${zipName}.zip"`,
    'cache-control': 'no-store'
  });

  for (const file of files) {
    const info = await stat(file.fullPath);
    const crc = await crc32File(file.fullPath);
    const name = Buffer.from(file.relativePath.replaceAll('\\', '/'), 'utf8');
    const localHeader = makeLocalHeader(name, crc, info.size);
    res.write(localHeader);
    offset += localHeader.length;
    await pipeFile(file.fullPath, res);
    central.push({ name, crc, size: info.size, offset: offset - localHeader.length });
    offset += info.size;
  }

  const centralStart = offset;
  for (const entry of central) {
    const header = makeCentralHeader(entry);
    res.write(header);
    offset += header.length;
  }
  res.end(makeEndRecord(central.length, offset - centralStart, centralStart));
}

async function collectFiles(root) {
  const files = [];
  async function walk(dir, prefix = '') {
    const entries = await readdir(dir, { withFileTypes: true });
    for (const entry of entries) {
      const fullPath = path.join(dir, entry.name);
      const relativePath = path.join(prefix, entry.name);
      if (entry.isDirectory()) {
        await walk(fullPath, relativePath);
      } else {
        files.push({ fullPath, relativePath });
      }
    }
  }
  await walk(root);
  return files;
}

function makeLocalHeader(name, crc, size) {
  const buffer = Buffer.alloc(30 + name.length);
  buffer.writeUInt32LE(0x04034b50, 0);
  buffer.writeUInt16LE(20, 4);
  buffer.writeUInt16LE(0x0800, 6);
  buffer.writeUInt16LE(0, 8);
  buffer.writeUInt16LE(0, 10);
  buffer.writeUInt16LE(0, 12);
  buffer.writeUInt32LE(crc >>> 0, 14);
  buffer.writeUInt32LE(size, 18);
  buffer.writeUInt32LE(size, 22);
  buffer.writeUInt16LE(name.length, 26);
  buffer.writeUInt16LE(0, 28);
  name.copy(buffer, 30);
  return buffer;
}

function makeCentralHeader(entry) {
  const buffer = Buffer.alloc(46 + entry.name.length);
  buffer.writeUInt32LE(0x02014b50, 0);
  buffer.writeUInt16LE(20, 4);
  buffer.writeUInt16LE(20, 6);
  buffer.writeUInt16LE(0x0800, 8);
  buffer.writeUInt16LE(0, 10);
  buffer.writeUInt16LE(0, 12);
  buffer.writeUInt16LE(0, 14);
  buffer.writeUInt32LE(entry.crc >>> 0, 16);
  buffer.writeUInt32LE(entry.size, 20);
  buffer.writeUInt32LE(entry.size, 24);
  buffer.writeUInt16LE(entry.name.length, 28);
  buffer.writeUInt16LE(0, 30);
  buffer.writeUInt16LE(0, 32);
  buffer.writeUInt16LE(0, 34);
  buffer.writeUInt16LE(0, 36);
  buffer.writeUInt32LE(0, 38);
  buffer.writeUInt32LE(entry.offset, 42);
  entry.name.copy(buffer, 46);
  return buffer;
}

function makeEndRecord(count, centralSize, centralOffset) {
  const buffer = Buffer.alloc(22);
  buffer.writeUInt32LE(0x06054b50, 0);
  buffer.writeUInt16LE(0, 4);
  buffer.writeUInt16LE(0, 6);
  buffer.writeUInt16LE(count, 8);
  buffer.writeUInt16LE(count, 10);
  buffer.writeUInt32LE(centralSize, 12);
  buffer.writeUInt32LE(centralOffset, 16);
  buffer.writeUInt16LE(0, 20);
  return buffer;
}

function pipeFile(filePath, res) {
  return new Promise((resolve, reject) => {
    const stream = createReadStream(filePath);
    stream.on('error', reject);
    stream.on('end', resolve);
    stream.pipe(res, { end: false });
  });
}

function crc32File(filePath) {
  return new Promise((resolve, reject) => {
    let crc = 0 ^ -1;
    const stream = createReadStream(filePath);
    stream.on('data', (chunk) => {
      for (const byte of chunk) {
        crc = (crc >>> 8) ^ CRC_TABLE[(crc ^ byte) & 0xff];
      }
    });
    stream.on('error', reject);
    stream.on('end', () => resolve((crc ^ -1) >>> 0));
  });
}

function makeCrcTable() {
  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n += 1) {
    let c = n;
    for (let k = 0; k < 8; k += 1) {
      c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    }
    table[n] = c >>> 0;
  }
  return table;
}
