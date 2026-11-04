//! Windows 7 text fallback built on the Win32 GDI font APIs.
//!
//! The normal GPUI Windows backend uses DirectWrite 3/4/5 interfaces. Those
//! interfaces are not implemented by the Windows 7 DirectWrite runtime. This
//! backend preserves text layout and glyph rasterization through the older
//! GDI APIs that are available on Windows 7.

use std::{
    borrow::Cow,
    collections::HashMap,
};

use anyhow::{Context as _, Result, anyhow};
use gpui::*;
use parking_lot::RwLock;
use windows::{Win32::Graphics::Gdi::*};

const BASE_EM_SIZE: i32 = 2048;
const DEFAULT_FAMILY: &str = "Segoe UI";

#[derive(Default)]
struct GdiState {
    fonts: Vec<Font>,
    font_ids: HashMap<Font, FontId>,
    private_font_resources: Vec<isize>,
}

pub(crate) struct GdiTextSystem {
    state: RwLock<GdiState>,
}

impl GdiTextSystem {
    pub(crate) fn new() -> Self {
        Self {
            state: RwLock::new(GdiState::default()),
        }
    }

    fn font_descriptor(&self, font_id: FontId) -> Option<Font> {
        self.state.read().fonts.get(font_id.0).cloned()
    }

    fn font_metrics_for(font: &Font) -> FontMetrics {
        with_font(font, BASE_EM_SIZE as f32, |dc, dpi_scale| {
            let mut metrics = TEXTMETRICW::default();
            if !unsafe { GetTextMetricsW(dc, &mut metrics) }.as_bool() {
                return Err(anyhow!("GetTextMetricsW failed"));
            }

            let ascent = metrics.tmAscent as f32 / dpi_scale;
            let descent = metrics.tmDescent as f32 / dpi_scale;
            let height = (metrics.tmHeight as f32 / dpi_scale).max(1.0);
            let max_width = metrics.tmMaxCharWidth as f32 / dpi_scale;

            Ok(FontMetrics {
                units_per_em: BASE_EM_SIZE as u32,
                ascent,
                descent: -descent,
                line_gap: metrics.tmExternalLeading as f32 / dpi_scale,
                underline_position: -(BASE_EM_SIZE as f32 * 0.10),
                underline_thickness: (BASE_EM_SIZE as f32 * 0.05).max(1.0),
                cap_height: ascent * 0.72,
                x_height: ascent * 0.52,
                bounding_box: Bounds {
                    origin: point(0.0, -ascent),
                    size: size(max_width.max(1.0), height),
                },
            })
        })
        .unwrap_or(FontMetrics {
            units_per_em: BASE_EM_SIZE as u32,
            ascent: 1500.0,
            descent: -500.0,
            line_gap: 0.0,
            underline_position: -200.0,
            underline_thickness: 100.0,
            cap_height: 1400.0,
            x_height: 1000.0,
            bounding_box: Bounds {
                origin: point(0.0, -1500.0),
                size: size(2000.0, 2000.0),
            },
        })
    }

    fn glyph_metrics(font: &Font, glyph_id: GlyphId, height: f32) -> Result<(GLYPHMETRICS, f32)> {
        with_font(font, height, |dc, dpi_scale| {
            let mut metrics = GLYPHMETRICS::default();
            let transform = identity_mat2();
            let result = unsafe {
                GetGlyphOutlineW(
                    dc,
                    glyph_id.0,
                    GGO_METRICS | GGO_GLYPH_INDEX,
                    &mut metrics,
                    0,
                    None,
                    &transform,
                )
            };
            if result == GDI_ERROR {
                return Err(anyhow!("GetGlyphOutlineW failed for glyph {}", glyph_id.0));
            }
            Ok((metrics, dpi_scale))
        })
    }

    fn lookup_glyph(font: &Font, ch: char) -> Option<GlyphId> {
        with_font(font, BASE_EM_SIZE as f32, |dc, _| {
            let mut encoded = [0u16; 2];
            let utf16: Vec<u16> = ch.encode_utf16(&mut encoded).to_vec();
            let mut indices = vec![0u16; utf16.len()];
            let result = unsafe {
                GetGlyphIndicesW(
                    dc,
                    &utf16,
                    utf16.len() as i32,
                    indices.as_mut_ptr(),
                    GGI_MARK_NONEXISTING_GLYPHS,
                )
            };
            if result == GDI_ERROR || indices.is_empty() || indices[0] == 0xFFFF {
                return Ok(None);
            }
            // GDI's legacy mapper returns one glyph per UTF-16 code unit. A
            // supplementary character cannot be represented as a single glyph.
            if utf16.len() != 1 {
                return Ok(None);
            }
            Ok(Some(GlyphId(indices[0] as u32)))
        })
        .ok()
        .flatten()
    }

    fn measure_text(dc: HDC, text: &[u16]) -> Result<SIZE> {
        let mut extent = SIZE::default();
        if !unsafe { GetTextExtentPoint32W(dc, text, &mut extent) }.as_bool() {
            return Err(anyhow!("GetTextExtentPoint32W failed"));
        }
        Ok(extent)
    }

    fn layout_run(
        font: &Font,
        text: &str,
        base_byte_offset: usize,
        x_offset: f32,
        font_size: Pixels,
    ) -> Result<(ShapedRun, f32, f32, f32)> {
        with_font(font, font_size.as_f32(), |dc, dpi_scale| {
            let utf16: Vec<u16> = text.encode_utf16().collect();
            let mut indices = vec![0u16; utf16.len()];
            let converted = if utf16.is_empty() {
                0
            } else {
                unsafe {
                    GetGlyphIndicesW(
                        dc,
                        &utf16,
                        utf16.len() as i32,
                        indices.as_mut_ptr(),
                        GGI_MARK_NONEXISTING_GLYPHS,
                    )
                }
            };
            if converted == GDI_ERROR {
                return Err(anyhow!("GetGlyphIndicesW failed while laying out text"));
            }

            let mut glyphs = Vec::with_capacity(text.chars().count());
            let mut utf16_offset = 0usize;
            let mut previous_width = 0i32;

            for (byte_offset, ch) in text.char_indices() {
                let units = ch.len_utf16();
                let end = (utf16_offset + units).min(utf16.len());
                let extent = Self::measure_text(dc, &utf16[..end])?;
                let glyph_id = if units == 1 && indices[utf16_offset] != 0xFFFF {
                    indices[utf16_offset] as u32
                } else {
                    0
                };

                glyphs.push(ShapedGlyph {
                    id: GlyphId(glyph_id),
                    position: point(
                        px(x_offset + previous_width as f32 / dpi_scale),
                        px(0.0),
                    ),
                    index: base_byte_offset + byte_offset,
                    is_emoji: false,
                });
                previous_width = extent.cx;
                utf16_offset = end;
            }

            let mut metrics = TEXTMETRICW::default();
            if !unsafe { GetTextMetricsW(dc, &mut metrics) }.as_bool() {
                return Err(anyhow!("GetTextMetricsW failed during line layout"));
            }

            let ascent = metrics.tmAscent as f32 / dpi_scale;
            let descent = metrics.tmDescent as f32 / dpi_scale;
            let width = previous_width as f32 / dpi_scale;
            Ok((
                ShapedRun {
                    font_id: FontId(0),
                    glyphs,
                },
                width,
                ascent,
                descent,
            ))
        })
    }
}

impl Drop for GdiTextSystem {
    fn drop(&mut self) {
        for resource in self.state.get_mut().private_font_resources.drain(..) {
            unsafe {
                RemoveFontMemResourceEx(windows::Win32::Foundation::HANDLE(resource as _));
            }
        }
    }
}

impl PlatformTextSystem for GdiTextSystem {
    fn add_fonts(&self, fonts: Vec<Cow<'static, [u8]>>) -> Result<()> {
        let mut state = self.state.write();
        for font in fonts {
            if font.is_empty() || font.len() > u32::MAX as usize {
                continue;
            }
            let mut count = 0u32;
            let handle = unsafe {
                AddFontMemResourceEx(
                    font.as_ptr().cast(),
                    font.len() as u32,
                    None,
                    &mut count,
                )
            };
            if handle.is_invalid() {
                return Err(anyhow!("AddFontMemResourceEx failed to register an embedded font"));
            }
            state.private_font_resources.push(handle.0 as isize);
        }
        Ok(())
    }

    fn all_font_names(&self) -> Vec<String> {
        [
            DEFAULT_FAMILY,
            "Arial",
            "Arial Black",
            "Calibri",
            "Cambria",
            "Consolas",
            "Courier New",
            "Georgia",
            "Segoe UI",
            "Tahoma",
            "Times New Roman",
            "Trebuchet MS",
            "Verdana",
        ]
        .into_iter()
        .map(str::to_owned)
        .collect()
    }

    fn font_id(&self, descriptor: &Font) -> Result<FontId> {
        let mut state = self.state.write();
        if let Some(font_id) = state.font_ids.get(descriptor) {
            return Ok(*font_id);
        }

        let font_id = FontId(state.fonts.len());
        state.fonts.push(descriptor.clone());
        state.font_ids.insert(descriptor.clone(), font_id);
        Ok(font_id)
    }

    fn font_metrics(&self, font_id: FontId) -> FontMetrics {
        self.font_descriptor(font_id)
            .map(|font| Self::font_metrics_for(&font))
            .unwrap_or_else(|| Self::font_metrics_for(&Font::default()))
    }

    fn typographic_bounds(&self, font_id: FontId, glyph_id: GlyphId) -> Result<Bounds<f32>> {
        let font = self
            .font_descriptor(font_id)
            .ok_or_else(|| anyhow!("Unknown GDI font id {}", font_id.0))?;
        let (metrics, dpi_scale) = Self::glyph_metrics(&font, glyph_id, BASE_EM_SIZE as f32)?;
        Ok(Bounds {
            origin: point(
                metrics.gmptGlyphOrigin.x as f32 / dpi_scale,
                -(metrics.gmptGlyphOrigin.y as f32) / dpi_scale,
            ),
            size: size(
                metrics.gmBlackBoxX as f32 / dpi_scale,
                metrics.gmBlackBoxY as f32 / dpi_scale,
            ),
        })
    }

    fn advance(&self, font_id: FontId, glyph_id: GlyphId) -> Result<Size<f32>> {
        let font = self
            .font_descriptor(font_id)
            .ok_or_else(|| anyhow!("Unknown GDI font id {}", font_id.0))?;
        let (metrics, dpi_scale) = Self::glyph_metrics(&font, glyph_id, BASE_EM_SIZE as f32)?;
        Ok(size(metrics.gmCellIncX as f32 / dpi_scale, 0.0))
    }

    fn glyph_for_char(&self, font_id: FontId, ch: char) -> Option<GlyphId> {
        self.font_descriptor(font_id)
            .and_then(|font| Self::lookup_glyph(&font, ch))
    }

    fn glyph_raster_bounds(&self, params: &RenderGlyphParams) -> Result<Bounds<DevicePixels>> {
        let font = self
            .font_descriptor(params.font_id)
            .ok_or_else(|| anyhow!("Unknown GDI font id {}", params.font_id.0))?;
        let (metrics, _) = Self::glyph_metrics(
            &font,
            params.glyph_id,
            params.font_size.as_f32() * params.scale_factor,
        )?;
        Ok(Bounds {
            origin: point(
                DevicePixels(-metrics.gmptGlyphOrigin.x),
                DevicePixels(-metrics.gmptGlyphOrigin.y),
            ),
            size: size(
                DevicePixels(metrics.gmBlackBoxX as i32),
                DevicePixels(metrics.gmBlackBoxY as i32),
            ),
        })
    }

    fn rasterize_glyph(
        &self,
        params: &RenderGlyphParams,
        _raster_bounds: Bounds<DevicePixels>,
    ) -> Result<(Size<DevicePixels>, Vec<u8>)> {
        let font = self
            .font_descriptor(params.font_id)
            .ok_or_else(|| anyhow!("Unknown GDI font id {}", params.font_id.0))?;

        with_font(
            &font,
            params.font_size.as_f32() * params.scale_factor,
            |dc, _| {
                let transform = identity_mat2();
                let mut metrics = GLYPHMETRICS::default();
                let format = GGO_GRAY8_BITMAP | GGO_GLYPH_INDEX;
                let buffer_size = unsafe {
                    GetGlyphOutlineW(
                        dc,
                        params.glyph_id.0,
                        format,
                        &mut metrics,
                        0,
                        None,
                        &transform,
                    )
                };
                if buffer_size == GDI_ERROR {
                    return Err(anyhow!(
                        "GDI could not rasterize glyph {}",
                        params.glyph_id.0
                    ));
                }
                let width = metrics.gmBlackBoxX as usize;
                let height = metrics.gmBlackBoxY as usize;
                if width == 0 || height == 0 || buffer_size == 0 {
                    return Ok((size(DevicePixels(0), DevicePixels(0)), Vec::new()));
                }

                let stride = (width + 3) & !3;
                let required = stride
                    .checked_mul(height)
                    .ok_or_else(|| anyhow!("GDI glyph bitmap dimensions overflow"))?;
                let mut source = vec![0u8; required.max(buffer_size as usize)];
                let written = unsafe {
                    GetGlyphOutlineW(
                        dc,
                        params.glyph_id.0,
                        format,
                        &mut metrics,
                        source.len() as u32,
                        Some(source.as_mut_ptr().cast()),
                        &transform,
                    )
                };
                if written == GDI_ERROR {
                    return Err(anyhow!("GDI glyph bitmap extraction failed"));
                }

                let mut alpha = vec![0u8; width * height];
                for y in 0..height {
                    let source_y = height - 1 - y;
                    for x in 0..width {
                        let coverage = source[source_y * stride + x].min(64);
                        alpha[y * width + x] = ((coverage as u16 * 255 + 32) / 64) as u8;
                    }
                }
                Ok((
                    size(DevicePixels(width as i32), DevicePixels(height as i32)),
                    alpha,
                ))
            },
        )
    }

    fn layout_line(&self, text: &str, font_size: Pixels, runs: &[FontRun]) -> LineLayout {
        let mut layout = LineLayout {
            font_size,
            len: text.len(),
            ..Default::default()
        };
        let mut byte_offset = 0usize;

        for run in runs {
            if byte_offset >= text.len() {
                break;
            }
            let end = (byte_offset + run.len).min(text.len());
            if !text.is_char_boundary(end) {
                break;
            }
            let Some(font) = self.font_descriptor(run.font_id) else {
                byte_offset = end;
                continue;
            };
            let segment = &text[byte_offset..end];
            let shaped = Self::layout_run(
                &font,
                segment,
                byte_offset,
                layout.width.as_f32(),
                font_size,
            );

            if let Ok((mut shaped_run, width, ascent, descent)) = shaped {
                shaped_run.font_id = run.font_id;
                if !shaped_run.glyphs.is_empty() {
                    layout.runs.push(shaped_run);
                }
                layout.width += px(width);
                layout.ascent = layout.ascent.max(px(ascent));
                layout.descent = layout.descent.max(px(descent));
            }
            byte_offset = end;
        }

        layout
    }

    fn recommended_rendering_mode(
        &self,
        _font_id: FontId,
        _font_size: Pixels,
    ) -> TextRenderingMode {
        TextRenderingMode::Grayscale
    }
}

fn identity_mat2() -> MAT2 {
    MAT2 {
        eM11: FIXED { fract: 0, value: 1 },
        eM12: FIXED::default(),
        eM21: FIXED::default(),
        eM22: FIXED { fract: 0, value: 1 },
    }
}

fn with_font<T>(
    descriptor: &Font,
    font_size: f32,
    callback: impl FnOnce(HDC, f32) -> Result<T>,
) -> Result<T> {
    let dc = unsafe { GetDC(None) };
    if dc.is_invalid() {
        return Err(anyhow!("GetDC failed for GDI text rendering"));
    }

    let dpi = unsafe { GetDeviceCaps(Some(dc), LOGPIXELSX) };
    let dpi_scale = if dpi > 0 {
        dpi as f32 / 96.0
    } else {
        1.0
    };

    let mut logfont = LOGFONTW::default();
    logfont.lfHeight = -(font_size * dpi_scale).round().max(1.0) as i32;
    logfont.lfWeight = descriptor.weight.0.round() as i32;
    logfont.lfItalic = u8::from(descriptor.style != FontStyle::Normal);
    logfont.lfQuality = CLEARTYPE_QUALITY.0 as u8;

    let family = if descriptor.family.as_str() == ".SystemUIFont" {
        DEFAULT_FAMILY
    } else {
        descriptor.family.as_str()
    };
    let face_name_len = logfont.lfFaceName.len().saturating_sub(1);
    for (target, source) in logfont
        .lfFaceName
        .iter_mut()
        .take(face_name_len)
        .zip(family.encode_utf16())
    {
        *target = source;
    }

    let font = unsafe { CreateFontIndirectW(&logfont) };
    if font.is_invalid() {
        unsafe {
            ReleaseDC(None, dc);
        }
        return Err(anyhow!("CreateFontIndirectW failed for {family}"));
    }

    let old_font = unsafe { SelectObject(dc, HGDIOBJ(font.0)) };
    if old_font.is_invalid() {
        unsafe {
            DeleteObject(HGDIOBJ(font.0));
            ReleaseDC(None, dc);
        }
        return Err(anyhow!("SelectObject failed for GDI font {family}"));
    }

    let result = callback(dc, dpi_scale);

    unsafe {
        SelectObject(dc, old_font);
        DeleteObject(HGDIOBJ(font.0));
        ReleaseDC(None, dc);
    }

    result.with_context(|| format!("GDI text operation failed for font {family}"))
}
