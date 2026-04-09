/// Build sorted KTX2 key/value data for `KTXorientation` and `KTXwriter`.
///
/// Keys must be sorted by Unicode code point order; "KTXorientation" < "KTXwriter".
/// Each entry: `keyAndValueByteLength u32` + key NUL-terminated + value NUL-terminated,
/// followed by padding to align the next entry on a 4-byte boundary.
pub(crate) fn build_kv_data(writer: &str) -> Vec<u8> {
    let mut out = Vec::new();

    // Entry 1: KTXorientation = "rd" (right-down: standard top-left origin)
    push_kv_entry(&mut out, b"KTXorientation\0", b"rd\0");

    // Entry 2: KTXwriter = caller-provided generator string
    let writer_value = format!("{writer}\0");
    push_kv_entry(&mut out, b"KTXwriter\0", writer_value.as_bytes());

    out
}

fn push_kv_entry(out: &mut Vec<u8>, key: &[u8], value: &[u8]) {
    let kv_len = key.len() + value.len();
    out.extend_from_slice(&(kv_len as u32).to_le_bytes());
    out.extend_from_slice(key);
    out.extend_from_slice(value);
    let pad = (4usize.wrapping_sub(kv_len % 4)) % 4;
    out.extend(std::iter::repeat(0u8).take(pad));
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn kv_data_starts_with_orientation() {
        let bytes = build_kv_data("test writer");
        // First 4 bytes = length of first key+value ("KTXorientation\0rd\0" = 18)
        let first_len = u32::from_le_bytes(bytes[0..4].try_into().unwrap());
        assert_eq!(first_len, 18);
        assert_eq!(&bytes[4..19], b"KTXorientation\0");
        assert_eq!(&bytes[19..22], b"rd\0");
    }

    #[test]
    fn kv_data_total_length_is_4_byte_aligned_per_entry() {
        let bytes = build_kv_data("ibl-baker");
        // Walk entries and check each is 4-byte sized (4 + kv_len + pad).
        let mut pos = 0usize;
        while pos < bytes.len() {
            let kv_len = u32::from_le_bytes(bytes[pos..pos + 4].try_into().unwrap()) as usize;
            let entry_total = 4 + kv_len + (4usize.wrapping_sub(kv_len % 4)) % 4;
            assert_eq!(entry_total % 4, 0);
            pos += entry_total;
        }
        assert_eq!(pos, bytes.len());
    }
}
