"""GPU orthographic globe: camera and time changes update uniforms, not pixels."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from math import radians
from time import perf_counter

from OpenGL.GL import (
    GL_ARRAY_BUFFER, GL_CLAMP_TO_EDGE, GL_COLOR_BUFFER_BIT, GL_COMPILE_STATUS,
    GL_FALSE, GL_FLOAT, GL_FRAGMENT_SHADER, GL_HALF_FLOAT, GL_LINEAR, GL_LINEAR_MIPMAP_LINEAR,
    GL_LINK_STATUS, GL_RGB,
    GL_RGB8, GL_RGB16F, GL_RGB32F, GL_REPEAT, GL_TEXTURE0, GL_TEXTURE1, GL_TEXTURE2, GL_TEXTURE_2D,
    GL_TEXTURE_MAG_FILTER, GL_TEXTURE_MIN_FILTER, GL_TEXTURE_WRAP_S,
    GL_TEXTURE_WRAP_T, GL_TRIANGLES, GL_UNPACK_ALIGNMENT,
    GL_VERTEX_SHADER, glActiveTexture, glAttachShader, glBindTexture,
    glBindVertexArray, glClear, glClearColor, glCompileShader,
    glCreateProgram, glCreateShader, glDeleteProgram, glDeleteShader,
    glDeleteTextures, glDrawArrays, glGenTextures, glGenVertexArrays,
    glGenerateMipmap, glGetFloatv,
    glGetProgramInfoLog, glGetProgramiv, glGetShaderInfoLog, glGetShaderiv,
    glLinkProgram, glPixelStorei, glShaderSource, glTexImage2D,
    glTexParameterf, glTexParameteri, glUniform1f, glUniform1i, glUniform2f, glUseProgram,
    glViewport,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPainter
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QWidget


MAX_ZOOM = 12.0
DEFAULT_SHARPNESS = 120
MAX_SHARPNESS = 200


VERTEX = """#version 330 core
out vec2 uv;
void main() {
    vec2 points[3] = vec2[3](vec2(-1.0,-1.0), vec2(3.0,-1.0), vec2(-1.0,3.0));
    gl_Position = vec4(points[gl_VertexID], 0.0, 1.0);
    uv = points[gl_VertexID] * 0.5 + 0.5;
}
"""

FRAGMENT = """#version 330 core
in vec2 uv;
out vec4 frag;
uniform sampler2D mapImage;
uniform sampler2D oldSurface;
uniform sampler2D paletteImage;
uniform float timeBlend;
uniform vec2 sizePx;
uniform float radiusPx;
uniform float cameraLon;
uniform float cameraLat;
uniform float sharpness;
uniform float fineDetail;
uniform bool gridNodes;
const float PI = 3.141592653589793;
vec4 surfaceColor(vec2 coord, vec2 gx, vec2 gy) {
    vec3 surface = textureGrad(mapImage, coord, gx, gy).rgb;
    if (!gridNodes) return vec4(surface, 1.0);
    if (timeBlend > 0.0) {
        surface = mix(surface, textureGrad(oldSurface, coord, gx, gy).rgb, timeBlend);
    }
    // Interpolate one numeric surface first. A single sea/land decision keeps
    // the coastline opaque; colors from two independent maps are never mixed.
    float height = surface.x;
    bool sea = height < 0.0;
    float level = sea ? clamp((height + 5200.0) / 5200.0, 0.0, 1.0)
                      : clamp(height / 4300.0, 0.0, 1.0);
    float paletteWidth = float(textureSize(paletteImage, 0).x);
    vec2 paletteUv = vec2((level * (paletteWidth - 1.0) + 0.5) / paletteWidth,
                          sea ? 0.25 : 0.75);
    vec3 color = textureLod(paletteImage, paletteUv, 0.0).rgb;
    // Soft directional relief, with a weaker fill light. There is no specular
    // highlight; shallow seas read mainly through depth color.
    float strength = clamp(sharpness, 0.0, 2.0);
    float normalScale = 0.0055 * (1.0 + 0.38 * strength);
    vec3 normal = normalize(vec3(-surface.y * normalScale, -surface.z * normalScale, 1.0));
    float key = max(dot(normal, normalize(vec3(-0.55, 0.65, 0.95))), 0.0);
    float fill = max(dot(normal, normalize(vec3(0.65, 0.15, 1.0))), 0.0);
    float shade = 0.715 + 0.36 * key + 0.05 * fill;
    shade = clamp(1.024 + (shade - 1.024) * (1.0 + 0.24 * strength), 0.63, 1.18);
    if (sea) shade = mix(1.0, shade, 0.45);
    return vec4(color * shade, sea ? 0.0 : 1.0);
}
vec3 mapColor(sampler2D image, vec2 coord, vec2 dx, vec2 dy) {
    vec2 dimensions = vec2(textureSize(image, 0));
    if (gridNodes) {
        // Numeric grids include both poles and one copy of the antimeridian.
        // Align their geographic nodes with texel centers, not texel edges.
        vec2 scale = vec2(1.0, (dimensions.y - 1.0) / dimensions.y);
        coord = coord * scale + 0.5 / dimensions;
        dx *= scale;
        dy *= scale;
    }
    // Height filtering stays fixed: changing sharpness must not move a coast.
    vec2 gx = dx;
    vec2 gy = dy;
    float strength = clamp(sharpness, 0.0, 2.0);
    vec4 center = surfaceColor(coord, gx, gy);
    if (strength < 0.001) return center.rgb;
    // Match local contrast to the source grid and the current screen scale.
    float radius = 0.7 + 0.65 * strength;
    // At extreme zoom one grid cell spans many screen pixels. Limit the
    // contrast kernel to a few pixels, rather than embossing large cell blocks.
    float scaleX = clamp(1.0 / max(length(dx * dimensions), 0.0001), 1.0, 3.0);
    float scaleY = clamp(1.0 / max(length(dy * dimensions), 0.0001), 1.0, 3.0);
    vec2 sx = radius * dx * scaleX;
    vec2 sy = radius * dy * scaleY;
    vec4 a = surfaceColor(coord + sx, gx, gy);
    vec4 b = surfaceColor(coord - sx, gx, gy);
    vec4 c = surfaceColor(coord + sy, gx, gy);
    vec4 d = surfaceColor(coord - sy, gx, gy);
    // Ignore samples across a coast, keeping pale water out of land shadows.
    vec4 weight = vec4(1.0) - step(vec4(0.5), abs(vec4(a.a, b.a, c.a, d.a) - center.a));
    float total = dot(weight, vec4(1.0));
    vec3 nearby = (a.rgb * weight.x + b.rgb * weight.y + c.rgb * weight.z + d.rgb * weight.w
                   + center.rgb) / (total + 1.0);
    // Luminance contrast has a soft shoulder, so the slider never hits the old
    // early hard ceiling. Color ratios and opaque coast geometry are retained.
    const vec3 luma = vec3(0.2126, 0.7152, 0.0722);
    float luminance = dot(center.rgb, luma);
    float detail = dot(center.rgb - nearby, luma);
    detail *= smoothstep(0.25 / 255.0, 1.0 / 255.0, abs(detail));
    float limit = 0.02 + 0.025 * strength;
    float correction = limit * tanh(detail * strength * 2.8 * fineDetail / limit);
    float gain = max(0.0, luminance + correction) / max(luminance, 0.001);
    return clamp(center.rgb * gain, 0.0, 1.0);
}
float hash21(vec2 p) {
    p = fract(p * vec2(123.34, 456.21));
    p += dot(p, p + 45.32);
    return fract(p.x * p.y);
}
void main() {
    vec2 position = (gl_FragCoord.xy - sizePx * 0.5) / radiusPx;
    float r2 = dot(position, position);
    vec3 background = vec3(0.014, 0.056, 0.099);
    vec2 starGrid = gl_FragCoord.xy / 48.0;
    vec2 starCell = floor(starGrid);
    vec2 starOffset = vec2(hash21(starCell + 17.7), hash21(starCell + 53.1)) - 0.5;
    float starDistance = length(fract(starGrid) - 0.5 - starOffset);
    float starChance = step(0.992, hash21(starCell));
    float star = starChance * (1.0 - smoothstep(0.006, 0.045, starDistance));
    background += vec3(0.48, 0.56, 0.65) * star * 0.25;
    float glow = exp(-pow(max(sqrt(r2)-1.0, 0.0)*radiusPx/22.0,2.0));
    background += vec3(0.008, 0.025, 0.040)*glow*0.22;
    float z = sqrt(max(0.0, 1.0-r2));
    float latitude = asin(clamp(z*sin(cameraLat) + position.y*cos(cameraLat), -1.0, 1.0));
    float longitude = atan(position.x, z*cos(cameraLat)-position.y*sin(cameraLat)) + cameraLon;
    vec2 mapUv = vec2(longitude/(2.0*PI)+0.5, latitude/PI+0.5);
    // Compute derivatives before branching, and unwrap the longitude seam.
    // Implicit derivatives of fract() selected blurry mip levels at that seam.
    vec2 dx = dFdx(mapUv);
    vec2 dy = dFdy(mapUv);
    dx.x -= round(dx.x);
    dy.x -= round(dy.x);
    float edgeWidth = 0.8 / radiusPx;
    if (sqrt(r2) >= 1.0 + edgeWidth) { frag = vec4(background, 1.0); return; }
    vec3 color = mapColor(mapImage, mapUv, dx, dy);
    float luminance = dot(color, vec3(0.2126, 0.7152, 0.0722));
    color = mix(vec3(luminance), color, 1.03);
    color = clamp((color - 0.5) * 1.035 + 0.5, 0.0, 1.0);
    float light = clamp(0.90 + 0.13*dot(vec3(position,z),normalize(vec3(-0.42,0.42,0.94))),0.82,1.03);
    color *= light;
    float rim = pow(1.0-z,5.0);
    color = mix(color, vec3(0.30,0.43,0.55),rim*0.10);
    float edge = 1.0-smoothstep(1.0-edgeWidth,1.0+edgeWidth,sqrt(r2));
    frag = vec4(mix(background,color,edge),1.0);
}
"""


def _shader(source, kind):
    shader = glCreateShader(kind)
    glShaderSource(shader, source)
    glCompileShader(shader)
    if not glGetShaderiv(shader, GL_COMPILE_STATUS):
        raise RuntimeError(glGetShaderInfoLog(shader).decode("utf-8", "replace"))
    return shader


class GlobeOverlay(QWidget):
    def __init__(self, globe):
        super().__init__(globe)
        self.globe = globe
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAutoFillBackground(False)

    def paintEvent(self, event):
        if not self.globe.overlay:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        self.globe.overlay(painter, self.width()/2, self.height()/2,
                           min(self.width()*.39, self.height()*.48)*self.globe.zoom)
        painter.end()


class GlobeWidget(QOpenGLWidget):
    image_ready = Signal(object, object)
    frame_changed = Signal(str, float)
    fps_changed = Signal(float)

    def __init__(self, data, parent=None):
        super().__init__(parent)
        self.data = data
        self.setMinimumSize(480, 360)
        self.setMouseTracking(True)
        self.camera_lon = 65.0
        self.camera_lat = 55.0
        self.zoom = 1.0
        self.sharpness = DEFAULT_SHARPNESS / 100.0
        self.age = 140.0
        self.overlay = None
        self.target = None
        self.displayed_frame = None
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="paleodem")
        self._requested = set()
        self._decoded = {}
        self._textures = {}
        self._texture_order = []
        self._program = None
        self._vao = None
        self._palette = None
        self._anisotropy = 1.0
        self._closed = False
        self._drag = None
        self._fps_frames = 0
        self._fps_since = perf_counter()
        self.image_ready.connect(self._accept_image)
        self.camera_changed = None
        self.zoom_changed = None
        self.overlay_widget = GlobeOverlay(self)
        self.overlay_widget.setGeometry(self.rect())
        self.overlay_widget.raise_()

    def close_data(self):
        if self._closed:
            return
        self._closed = True
        self._executor.shutdown(wait=False, cancel_futures=True)
        if self._program:
            self.makeCurrent()
            if self._textures:
                glDeleteTextures(list(self._textures.values()))
            if self._palette:
                glDeleteTextures([self._palette])
                self._palette = None
            glDeleteProgram(self._program)
            self._program = None
            self._textures.clear()
            self.doneCurrent()

    def set_age(self, age):
        self.age = float(age)
        self.target = self.data.frames(self.age)
        mode, younger, older, _ = self.target
        for date in {younger, older}:
            self._request(mode, date)
        # Prepare neighboring source grids in either direction.
        ages = self.data.ages if mode == "dem" else self.data.old_ages
        for neighbor in (ages.index(younger) - 1, ages.index(older) + 1):
            if 0 <= neighbor < len(ages):
                self._request(mode, ages[neighbor])
        self.update()

    def _request(self, mode, age):
        key = mode, age
        if key in self._requested or key in self._textures or key in self._decoded:
            return
        self._requested.add(key)
        future = self._executor.submit(self.data.texture, mode, age)
        future.add_done_callback(lambda f, k=key: self._finish_request(k, f))

    def _finish_request(self, key, future):
        if self._closed or future.cancelled():
            return
        try:
            image = future.result()
        except Exception as exc:
            self.image_ready.emit(key, exc)
        else:
            self.image_ready.emit(key, image)

    def _accept_image(self, key, image):
        if self._closed:
            return
        self._requested.discard(key)
        if isinstance(image, Exception):
            if hasattr(self, "show_error"):
                self.show_error(str(image))
            return
        self._decoded[key] = image
        self.update()

    def initializeGL(self):
        vertex = _shader(VERTEX, GL_VERTEX_SHADER)
        fragment = _shader(FRAGMENT, GL_FRAGMENT_SHADER)
        program = glCreateProgram()
        glAttachShader(program, vertex)
        glAttachShader(program, fragment)
        glLinkProgram(program)
        glDeleteShader(vertex)
        glDeleteShader(fragment)
        if not glGetProgramiv(program, GL_LINK_STATUS):
            raise RuntimeError(glGetProgramInfoLog(program).decode("utf-8", "replace"))
        self._program = program
        self._vao = glGenVertexArrays(1)
        context = self.context()
        if (context.hasExtension(b"GL_EXT_texture_filter_anisotropic") or
                context.hasExtension(b"GL_ARB_texture_filter_anisotropic")):
            self._anisotropy = min(8.0, float(glGetFloatv(0x84FF)))
        self._palette = glGenTextures(1)
        glBindTexture(GL_TEXTURE_2D, self._palette)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
        palette = self.data.palette_texture()
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGB32F, palette.shape[1], palette.shape[0],
                     0, GL_RGB, GL_FLOAT, palette)
        glBindTexture(GL_TEXTURE_2D, 0)
        glClearColor(0.014, 0.056, 0.099, 1.0)

    def resizeGL(self, width, height):
        glViewport(0, 0, width, height)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.overlay_widget.setGeometry(self.rect())
        self.overlay_widget.raise_()

    def _upload(self, key, image):
        if key in self._textures:
            return
        texture = glGenTextures(1)
        glBindTexture(GL_TEXTURE_2D, texture)
        glPixelStorei(GL_UNPACK_ALIGNMENT, 1)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR_MIPMAP_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        if self._anisotropy > 1.0:
            glTexParameterf(GL_TEXTURE_2D, 0x84FE, self._anisotropy)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
        if key[0] == "dem":
            # Upload IEEE half-float bytes directly, avoiding array conversion.
            glTexImage2D(GL_TEXTURE_2D, 0, GL_RGB16F, image.shape[1], image.shape[0],
                         0, GL_RGB, GL_HALF_FLOAT, image.tobytes())
        else:
            glTexImage2D(GL_TEXTURE_2D, 0, GL_RGB8, image.shape[1], image.shape[0],
                         0, GL_RGB, 0x1401, image)
        glGenerateMipmap(GL_TEXTURE_2D)
        self._textures[key] = texture
        self._texture_order.append(key)
        while len(self._texture_order) > 6:
            old_key = self._texture_order.pop(0)
            if self.target and old_key in ((self.target[0], self.target[1]),
                                          (self.target[0], self.target[2])):
                self._texture_order.append(old_key)
                continue
            glDeleteTextures([self._textures.pop(old_key)])

    def paintGL(self):
        dpr = self.devicePixelRatioF()
        width = max(1, round(self.width() * dpr))
        height = max(1, round(self.height() * dpr))
        glViewport(0, 0, width, height)
        glClear(GL_COLOR_BUFFER_BIT)
        for key in list(self._decoded):
            # Large uploads happen only at published map boundaries.
            if key not in self._textures:
                self._upload(key, self._decoded.pop(key))
        if self.target:
            mode, younger, older, fraction = self.target
            first = self._textures.get((mode, younger))
            second = self._textures.get((mode, older))
            frame = mode, self.age if mode == "dem" else younger
            if first is None or second is None:
                available = [(key, val) for key, val in self._textures.items() if key[0] == mode]
                if available:
                    frame, first = min(available, key=lambda item: abs(item[0][1]-self.age))
                    second = first
                    fraction = 0.0
                    younger = older = frame[1]
            if first and second:
                glUseProgram(self._program)
                glBindVertexArray(self._vao)
                glActiveTexture(GL_TEXTURE0)
                glBindTexture(GL_TEXTURE_2D, first)
                glActiveTexture(GL_TEXTURE1)
                glBindTexture(GL_TEXTURE_2D, second)
                glActiveTexture(GL_TEXTURE2)
                glBindTexture(GL_TEXTURE_2D, self._palette)
                from OpenGL.GL import glGetUniformLocation
                u = lambda name: glGetUniformLocation(self._program, name)
                glUniform1i(u("mapImage"), 0)
                glUniform1i(u("oldSurface"), 1)
                glUniform1i(u("paletteImage"), 2)
                glUniform1f(u("timeBlend"), fraction)
                glUniform1f(u("sharpness"), self.sharpness)
                # Sparse ancient relief has smooth hills quantized in 40 m
                # steps. Emphasize its lighting without engraving those steps.
                detail_scale = ((1.0 - fraction) * (0.3 if younger > 540 else 1.0)
                                + fraction * (0.3 if older > 540 else 1.0))
                glUniform1f(u("fineDetail"), detail_scale)
                glUniform1i(u("gridNodes"), int(mode == "dem"))
                glUniform2f(u("sizePx"), width, height)
                glUniform1f(u("radiusPx"), min(width * .39, height * .48) * self.zoom)
                glUniform1f(u("cameraLon"), radians(self.camera_lon))
                glUniform1f(u("cameraLat"), radians(self.camera_lat))
                glDrawArrays(GL_TRIANGLES, 0, 3)
                glUseProgram(0)
                glActiveTexture(GL_TEXTURE2)
                glBindTexture(GL_TEXTURE_2D, 0)
                glActiveTexture(GL_TEXTURE1)
                glBindTexture(GL_TEXTURE_2D, 0)
                glActiveTexture(GL_TEXTURE0)
                glBindTexture(GL_TEXTURE_2D, 0)
                glBindVertexArray(0)
                if self.displayed_frame != frame:
                    self.displayed_frame = frame
                    self.frame_changed.emit(*frame)
        if self.overlay:
            self.overlay_widget.update()
        self._fps_frames += 1
        now = perf_counter()
        elapsed = now - self._fps_since
        if elapsed >= 1.0:
            self.fps_changed.emit(self._fps_frames / elapsed)
            self._fps_frames = 0
            self._fps_since = now

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag = (event.position().x(), event.position().y(),
                          self.camera_lon, self.camera_lat)

    def mouseMoveEvent(self, event):
        if self._drag:
            x, y, lon, lat = self._drag
            sensitivity = .35 / max(1.0, self.zoom)
            self.camera_lon = (lon - (event.position().x()-x)*sensitivity + 180) % 360 - 180
            self.camera_lat = max(-85, min(85, lat + (event.position().y()-y)*sensitivity*.72))
            self.update()
            if self.camera_changed:
                self.camera_changed()

    def mouseReleaseEvent(self, event):
        self._drag = None

    def wheelEvent(self, event):
        steps = event.angleDelta().y()/120.0
        self.zoom = max(.7, min(MAX_ZOOM, self.zoom * (1.18 ** steps)))
        self.update()
        if self.zoom_changed:
            self.zoom_changed()
