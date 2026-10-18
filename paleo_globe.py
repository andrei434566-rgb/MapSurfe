"""GPU orthographic globe: camera and time changes update uniforms, not pixels."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from math import radians
from time import perf_counter

from OpenGL.GL import (
    GL_ARRAY_BUFFER, GL_CLAMP_TO_EDGE, GL_COLOR_BUFFER_BIT, GL_COMPILE_STATUS,
    GL_FALSE, GL_FRAGMENT_SHADER, GL_LINEAR, GL_LINK_STATUS, GL_RGB,
    GL_RGB8, GL_REPEAT, GL_TEXTURE0, GL_TEXTURE1, GL_TEXTURE_2D,
    GL_TEXTURE_MAG_FILTER, GL_TEXTURE_MIN_FILTER, GL_TEXTURE_WRAP_S,
    GL_TEXTURE_WRAP_T, GL_TRIANGLES, GL_UNPACK_ALIGNMENT,
    GL_VERTEX_SHADER, glActiveTexture, glAttachShader, glBindTexture,
    glBindVertexArray, glClear, glClearColor, glCompileShader,
    glCreateProgram, glCreateShader, glDeleteProgram, glDeleteShader,
    glDeleteTextures, glDrawArrays, glGenTextures, glGenVertexArrays,
    glGetProgramInfoLog, glGetProgramiv, glGetShaderInfoLog, glGetShaderiv,
    glLinkProgram, glPixelStorei, glShaderSource, glTexImage2D,
    glTexParameteri, glUniform1f, glUniform1i, glUniform2f, glUseProgram,
    glViewport,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPainter
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QWidget


MAX_ZOOM = 12.0


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
uniform sampler2D map0;
uniform sampler2D map1;
uniform float blend;
uniform vec2 sizePx;
uniform float radiusPx;
uniform float cameraLon;
uniform float cameraLat;
const float PI = 3.141592653589793;
void main() {
    vec2 position = (gl_FragCoord.xy - sizePx * 0.5) / radiusPx;
    float r2 = dot(position, position);
    vec3 background = vec3(0.014, 0.056, 0.099);
    float glow = exp(-pow(max(sqrt(r2)-1.0, 0.0)*radiusPx/22.0,2.0));
    background += vec3(0.004, 0.070, 0.112)*glow*0.40;
    if (r2 >= 1.012) { frag = vec4(background, 1.0); return; }
    float z = sqrt(max(0.0, 1.0-r2));
    float latitude = asin(clamp(z*sin(cameraLat) + position.y*cos(cameraLat), -1.0, 1.0));
    float longitude = atan(position.x, z*cos(cameraLat)-position.y*sin(cameraLat)) + cameraLon;
    vec2 mapUv = vec2(fract(longitude/(2.0*PI)+0.5), latitude/PI+0.5);
    vec3 young = texture(map0, mapUv).rgb;
    vec3 old = texture(map1, mapUv).rgb;
    vec3 color = mix(young, old, blend);
    float light = clamp(0.78 + 0.31*dot(vec3(position,z),normalize(vec3(-0.42,0.42,0.94))),0.58,1.11);
    color *= light;
    float rim = pow(1.0-z,3.0);
    color = mix(color, vec3(0.12,0.70,0.89),rim*0.33);
    float edge = 1.0-smoothstep(0.992,1.010,sqrt(r2));
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
    fps_changed = Signal(float)

    def __init__(self, data, parent=None):
        super().__init__(parent)
        self.data = data
        self.setMinimumSize(480, 360)
        self.setMouseTracking(True)
        self.camera_lon = 65.0
        self.camera_lat = 55.0
        self.zoom = 1.0
        self.age = 140.0
        self.overlay = None
        self.target = None
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="paleodem")
        self._requested = set()
        self._decoded = {}
        self._textures = {}
        self._texture_order = []
        self._program = None
        self._vao = None
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
            glDeleteProgram(self._program)
            self._program = None
            self._textures.clear()
            self.doneCurrent()

    def set_age(self, age):
        self.age = float(age)
        self.target = self.data.frames(self.age)
        mode, younger, older, _mix = self.target
        for date in (younger, older):
            self._request(mode, date)
        # Decode the next map before playback reaches it.
        if mode != "bridge":
            ages = self.data.ages if mode == "dem" else self.data.old_ages
            index = ages.index(older)
            if index + 1 < len(ages):
                self._request(mode, ages[index + 1])
        self.update()

    def _request(self, mode, age):
        key = mode, age
        if key in self._requested or key in self._textures or key in self._decoded:
            return
        self._requested.add(key)
        future = self._executor.submit(self.data.image, mode, age)
        future.add_done_callback(lambda f, k=key: self._finish_request(k, f))

    def _finish_request(self, key, future):
        try:
            image = future.result()
        except Exception as exc:
            self.image_ready.emit(key, exc)
        else:
            self.image_ready.emit(key, image)

    def _accept_image(self, key, image):
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
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGB8, image.shape[1], image.shape[0],
                     0, GL_RGB, 0x1401, image)
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
            mode, younger, older, mixture = self.target
            first = self._textures.get((mode, younger))
            second = self._textures.get((mode, older))
            if first is None or second is None:
                available = [(key, val) for key, val in self._textures.items() if key[0] == mode]
                if available:
                    first = second = min(available, key=lambda item: abs(item[0][1]-self.age))[1]
                    mixture = 0.0
            if first and second:
                glUseProgram(self._program)
                glBindVertexArray(self._vao)
                glActiveTexture(GL_TEXTURE0)
                glBindTexture(GL_TEXTURE_2D, first)
                glActiveTexture(GL_TEXTURE1)
                glBindTexture(GL_TEXTURE_2D, second)
                from OpenGL.GL import glGetUniformLocation
                u = lambda name: glGetUniformLocation(self._program, name)
                glUniform1i(u("map0"), 0)
                glUniform1i(u("map1"), 1)
                glUniform1f(u("blend"), mixture)
                glUniform2f(u("sizePx"), width, height)
                glUniform1f(u("radiusPx"), min(width * .39, height * .48) * self.zoom)
                glUniform1f(u("cameraLon"), radians(self.camera_lon))
                glUniform1f(u("cameraLat"), radians(self.camera_lat))
                glDrawArrays(GL_TRIANGLES, 0, 3)
                glUseProgram(0)
                glActiveTexture(GL_TEXTURE1)
                glBindTexture(GL_TEXTURE_2D, 0)
                glActiveTexture(GL_TEXTURE0)
                glBindTexture(GL_TEXTURE_2D, 0)
                glBindVertexArray(0)
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
