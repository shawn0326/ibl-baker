const BC6H_BLOCK_SIZE = 4;
const BC6H_BYTES_PER_BLOCK = 16;

export interface BC6HCopyLayout {
  bytesPerRow: number;
  rowsPerImage: number;
  width: number;
  height: number;
}

export function isBC6HBaseDimensionSupported(width: number, height: number): boolean {
  return width > 0 && height > 0 && width % BC6H_BLOCK_SIZE === 0 && height % BC6H_BLOCK_SIZE === 0;
}

export function bc6hCopyLayout(width: number, height: number): BC6HCopyLayout {
  return {
    bytesPerRow: Math.ceil(width / BC6H_BLOCK_SIZE) * BC6H_BYTES_PER_BLOCK,
    rowsPerImage: Math.ceil(height / BC6H_BLOCK_SIZE),
    width: Math.ceil(width / BC6H_BLOCK_SIZE) * BC6H_BLOCK_SIZE,
    height: Math.ceil(height / BC6H_BLOCK_SIZE) * BC6H_BLOCK_SIZE,
  };
}
