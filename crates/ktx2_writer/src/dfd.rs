/// Data Format Descriptor for `VK_FORMAT_BC6H_UFLOAT_BLOCK` (VkFormat 131).
///
/// Fields (Khronos Data Format Specification 1.3, §5.6.7):
///   dfdTotalSize          = 44   (4 B header + 40 B descriptor block)
///   vendorId              = 0    (KHR)
///   descriptorType        = 0    (KHR basic)
///   versionNumber         = 2    (KDF 1.3)
///   descriptorBlockSize   = 40   (24 B fixed + 16 B × 1 sample)
///   colorModel            = 133  (KHR_DF_MODEL_BC6H)
///   colorPrimaries        = 1    (KHR_DF_PRIMARIES_BT709)
///   transferFunction      = 1    (KHR_DF_TRANSFER_LINEAR)
///   texelBlockDimension   = 3,3,0,0  (4×4 texel block, stored as dim-1)
///   bytesPlane0           = 16   (one 128-bit BC6H block per 4×4 region)
///   sample[0].bitOffset   = 0
///   sample[0].bitLength   = 127  (stored as bitLength-1 = 127 → 128 bits)
///   sample[0].channelType = 0    (KHR_DF_CHANNEL_BC6H_COLOR)
///   sample[0].qualifiers  = F    (bit[31] = 1: float data)
///   sample[0].lower       = 0.0  (0x00000000)
///   sample[0].upper       = 65504.0f (0x477FE000 = max UFLOAT16 as f32)
pub(crate) const BC6H_UFLOAT_DFD: [u8; 44] = [
    // dfdTotalSize = 44
    0x2C, 0x00, 0x00, 0x00,
    // vendorId[16:0]=0, descriptorType[30:16]=0
    0x00, 0x00, 0x00, 0x00,
    // versionNumber[15:0]=2, descriptorBlockSize[31:16]=40
    0x02, 0x00, 0x28, 0x00,
    // colorModel=133, colorPrimaries=1, transferFunction=1, flags=0
    0x85, 0x01, 0x01, 0x00,
    // texelBlockDimension[0..3] = 3, 3, 0, 0
    0x03, 0x03, 0x00, 0x00,
    // bytesPlane[0]=16, bytesPlane[1..3]=0
    0x10, 0x00, 0x00, 0x00,
    // bytesPlane[4..7]=0
    0x00, 0x00, 0x00, 0x00,
    // Sample 0, word 0: combined u32 = 0x807F_0000 (LE: 00 00 7F 80)
    //   bits[15:0]  = bitOffset      = 0x0000
    //   bits[23:16] = bitLength-1    = 0x7F (127)
    //   bits[27:24] = channelType    = 0x0
    //   bits[31:28] = qualifiers     = 0x8 (F bit only)
    0x00, 0x00, 0x7F, 0x80,
    // Sample 0, word 1: samplePosition[0..3] = 0
    0x00, 0x00, 0x00, 0x00,
    // Sample 0, word 2: sampleLower = 0.0f = 0x0000_0000
    0x00, 0x00, 0x00, 0x00,
    // Sample 0, word 3: sampleUpper = 65504.0f = 0x477F_E000
    0x00, 0xE0, 0x7F, 0x47,
];

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn dfd_total_size_field_equals_44() {
        let total = u32::from_le_bytes(BC6H_UFLOAT_DFD[0..4].try_into().unwrap());
        assert_eq!(total, 44);
    }

    #[test]
    fn dfd_color_model_is_bc6h() {
        // colorModel is the first byte of word 2 (byte offset 12)
        assert_eq!(BC6H_UFLOAT_DFD[12], 133); // KHR_DF_MODEL_BC6H
    }

    #[test]
    fn dfd_sample_upper_is_65504f() {
        let upper = f32::from_le_bytes(BC6H_UFLOAT_DFD[40..44].try_into().unwrap());
        assert!((upper - 65504.0_f32).abs() < 1.0);
    }
}
