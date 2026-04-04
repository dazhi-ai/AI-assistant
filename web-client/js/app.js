(function () {
  "use strict";

  // ============================================================
  // DOM 引用
  // ============================================================
  var wsUrlInput     = document.getElementById("wsUrlInput");
  var tokenInput     = document.getElementById("tokenInput");
  var connectBtn     = document.getElementById("connectBtn");
  var disconnectBtn  = document.getElementById("disconnectBtn");
  var sendTextBtn    = document.getElementById("sendTextBtn");
  var statusText     = document.getElementById("statusText");
  var statusDot      = document.getElementById("statusDot");
  var textInput      = document.getElementById("textInput");
  var audioFileInput = document.getElementById("audioFileInput");
  var sendAudioBtn   = document.getElementById("sendAudioBtn");
  var audioUploadText= document.getElementById("audioUploadText");
  var logBox         = document.getElementById("logBox");
  var qrText         = document.getElementById("qrText");
  var qrImage        = document.getElementById("qrImage");
  var audioPlayer    = document.getElementById("audioPlayer");
  var audioText      = document.getElementById("audioText");
  var effectText     = document.getElementById("effectText");
  var heartEffect    = document.getElementById("heartEffect");
  var live2dContainer= document.getElementById("live2dContainer");
  var modelText      = document.getElementById("modelText");
  var mouthBarInner  = document.getElementById("mouthBarInner");
  var chatHistory    = document.getElementById("chatHistory");
  var clearChatBtn   = document.getElementById("clearChatBtn");
  var settingsBtn    = document.getElementById("settingsBtn");
  var settingsPanel  = document.getElementById("settingsPanel");
  var settingsCloseBtn = document.getElementById("settingsCloseBtn");
  var voiceBtn       = document.getElementById("voiceBtn");
  // 天气 overlay
  var weatherOverlay = document.getElementById("weatherOverlay");
  var weatherCity    = document.getElementById("weatherCity");
  var weatherDays    = document.getElementById("weatherDays");

  // ============================================================
  // 状态变量
  // ============================================================
  var socket = null;
  var isConnected = false;
  var reconnectTimer = null;
  var pingTimer = null;
  var live2dLoaded = false;
  var audioCtx = null;
  var mouthRaf = null;
  var mediaSource = null;
  var mediaSourceUrl = null;
  var sourceBuffer = null;
  var sourceQueue = [];
  var useMse = false;
  var fallbackChunks = [];
  var userRequestedDisconnect = false;
  var isRecording = false;
  var recognition = null;

  var MODEL_URLS = {
    "default": "./assets/models/shizuku/shizuku.model.json",
    "sport":   "./assets/models/shizuku/shizuku.model.json",
    "cute":    "./assets/models/shizuku/shizuku.model.json",
    "tech":    "./assets/models/shizuku/shizuku.model.json"
  };

  // ============================================================
  // 工具函数
  // ============================================================

  function nowTs() { return Math.floor(Date.now() / 1000); }

  function traceId(prefix) { return prefix + "-" + String(Date.now()); }

  function timeLabel() {
    var d = new Date();
    var h = d.getHours();
    var m = d.getMinutes();
    return (h < 10 ? "0" : "") + h + ":" + (m < 10 ? "0" : "") + m;
  }

  function appendLog(label, obj) {
    if (!logBox) { return; }
    var text = "[" + new Date().toLocaleTimeString() + "] " + label + "\n";
    if (typeof obj === "string") {
      text += obj;
    } else {
      try { text += JSON.stringify(obj, null, 2); } catch (e) { text += String(obj); }
    }
    text += "\n\n";
    logBox.textContent = text + logBox.textContent;
  }

  function setStatus(text, dotClass) {
    if (statusText) { statusText.textContent = text; }
    if (statusDot) {
      statusDot.className = "status-dot " + (dotClass || "disconnected");
    }
  }

  function safeSend(type, payload, customTraceId) {
    if (!socket || socket.readyState !== 1) {
      appendLog("WARN", "当前未连接，消息未发送: " + type);
      return;
    }
    var message = {
      type: String(type || "").toUpperCase(),
      payload: payload || {},
      trace_id: customTraceId || traceId("client"),
      timestamp: nowTs()
    };
    socket.send(JSON.stringify(message));
    appendLog("SEND " + message.type, message);
  }

  // ============================================================
  // 聊天历史 —— 消息气泡
  // ============================================================

  /**
   * 添加一条消息气泡到聊天历史
   * @param {string} role  "user" | "ai" | "xiaozhi" | "system"
   * @param {string} text  消息内容
   */
  function addMessage(role, text) {
    if (!chatHistory || !text) { return; }

    var row = document.createElement("div");
    row.className = "msg-row" +
      (role === "user"   ? " msg-user" :
       role === "system" ? " msg-system" : " msg-ai");

    if (role === "ai" || role === "xiaozhi") {
      var av = document.createElement("div");
      av.className = "msg-avatar" + (role === "xiaozhi" ? " avatar-xiaozhi" : "");
      av.textContent = role === "xiaozhi" ? "小智" : "AI";
      row.appendChild(av);
    }

    var body = document.createElement("div");
    body.className = "msg-body";

    if (role !== "system") {
      var timeEl = document.createElement("div");
      timeEl.className = "msg-time";
      timeEl.textContent = timeLabel();
      body.appendChild(timeEl);
    }

    var bubble = document.createElement("div");
    bubble.className = "msg-bubble";
    bubble.textContent = text;
    body.appendChild(bubble);

    row.appendChild(body);
    chatHistory.appendChild(row);

    // 始终滚动到最新消息
    chatHistory.scrollTop = chatHistory.scrollHeight;
  }

  function clearChat() {
    if (!chatHistory) { return; }
    while (chatHistory.firstChild) {
      chatHistory.removeChild(chatHistory.firstChild);
    }
    addMessage("system", "聊天记录已清除");
  }

  if (clearChatBtn) { clearChatBtn.onclick = clearChat; }

  // ============================================================
  // 设置面板
  // ============================================================

  function openSettings() {
    if (settingsPanel) {
      settingsPanel.className = settingsPanel.className.replace(" hidden", "").replace("hidden", "");
    }
  }

  function closeSettings() {
    if (settingsPanel && settingsPanel.className.indexOf("hidden") === -1) {
      settingsPanel.className += " hidden";
    }
  }

  if (settingsBtn)      { settingsBtn.onclick      = openSettings; }
  if (settingsCloseBtn) { settingsCloseBtn.onclick = closeSettings; }

  // ============================================================
  // 语音输入
  // ============================================================

  function initVoiceInput() {
    var SpeechAPI = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechAPI) {
      if (voiceBtn) { voiceBtn.style.display = "none"; }
      appendLog("WARN", "当前浏览器不支持语音识别（需要 Chrome 33+）");
      return;
    }

    recognition = new SpeechAPI();
    recognition.lang = "zh-CN";
    recognition.continuous = false;
    recognition.interimResults = false;

    recognition.onstart = function () {
      isRecording = true;
      if (voiceBtn) { voiceBtn.className = "btn-voice recording"; }
      appendLog("INFO", "语音识别已开启...");
    };

    recognition.onresult = function (event) {
      var transcript = "";
      if (event.results && event.results.length > 0) {
        transcript = (event.results[0][0].transcript || "").trim();
      }
      if (transcript && textInput) {
        textInput.value = transcript;
        sendTextCommand(); // 识别后自动发送
      }
    };

    recognition.onerror = function (e) {
      isRecording = false;
      if (voiceBtn) { voiceBtn.className = "btn-voice"; }
      appendLog("WARN", "语音识别错误: " + (e.error || String(e)));
    };

    recognition.onend = function () {
      isRecording = false;
      if (voiceBtn) { voiceBtn.className = "btn-voice"; }
    };

    if (voiceBtn) {
      voiceBtn.onclick = function () {
        if (isRecording) {
          recognition.stop();
        } else {
          try { recognition.start(); } catch (err) {
            appendLog("WARN", "语音识别启动失败: " + String(err));
          }
        }
      };
    }
  }

  // ============================================================
  // 特效
  // ============================================================

  function playHeartEffect() {
    if (!heartEffect) { return; }
    heartEffect.className = "heart-effect run";
    setTimeout(function () { heartEffect.className = "heart-effect hidden"; }, 1100);
  }

  // ============================================================
  // QR 码
  // ============================================================

  function renderQRCode(payload) {
    var qrimg = payload.qrimg || "";
    var qrurl = payload.qrurl || "";
    if (qrImage) {
      if (qrimg) {
        qrImage.src = qrimg;
        qrImage.className = "qr-image";
      } else {
        qrImage.className = "qr-image hidden";
      }
    }
    if (qrText) {
      qrText.textContent = qrurl ? "二维码链接：" + qrurl : (qrimg ? "请扫码登录" : "二维码数据为空");
    }
  }

  // ============================================================
  // 天气 Overlay（左上角，最近3天）
  // ============================================================

  function renderWeatherOverlay(payload) {
    if (!weatherOverlay || !weatherCity || !weatherDays) { return; }

    var cityName = (payload.city || "") + " " + (payload.adm2 || payload.adm1 || "");
    weatherCity.textContent = cityName.trim();

    var forecast = payload.forecast || [];
    // 最多显示 3 天
    var days = forecast.slice(0, 3);

    while (weatherDays.firstChild) { weatherDays.removeChild(weatherDays.firstChild); }

    var labels = ["今天", "明天", "后天"];
    var i;
    for (i = 0; i < days.length; i += 1) {
      var d = days[i];
      var row = document.createElement("div");
      row.className = "weather-day-row";

      var lbl = document.createElement("div");
      lbl.className = "weather-day-label";
      lbl.textContent = labels[i] || d.date;

      var info = document.createElement("div");
      info.className = "weather-day-info";
      var cond = d.text_day || d.text_night || "";
      var temp = (d.temp_min || "?") + "~" + (d.temp_max || "?") + "°";
      info.textContent = cond + " " + temp;

      row.appendChild(lbl);
      row.appendChild(info);
      weatherDays.appendChild(row);
    }

    // 显示 overlay
    weatherOverlay.className = weatherOverlay.className.replace(" hidden", "").replace("hidden", "");
  }

  // ============================================================
  // 音频播放
  // ============================================================

  function playAudio() {
    var ret = audioPlayer.play();
    if (ret && typeof ret["catch"] === "function") {
      ret["catch"](function () {
        appendLog("WARN", "浏览器阻止了自动播放，请手动点击播放按钮。");
      });
    }
  }

  function renderAudio(payload) {
    var url = payload.url || "";
    if (!url) { return; }
    audioPlayer.src = url;
    if (audioText) { audioText.textContent = "播放地址：" + url; }
    playAudio();
  }

  // ============================================================
  // 口型动画（正弦波，兼容旧 WebView）
  // ============================================================

  function applyMouthValue(value) {
    var v = Math.max(0, Math.min(1, value));
    if (mouthBarInner) { mouthBarInner.style.width = String(Math.floor(v * 100)) + "%"; }
    window._live2dMouthValue = v;
  }

  function startMouthAnimation(durationMs) {
    stopMouthSync();
    var startTs = Date.now();
    function tick() {
      var elapsed = Date.now() - startTs;
      if (durationMs && elapsed >= durationMs) { applyMouthValue(0); mouthRaf = null; return; }
      var phase = elapsed / 1000 * 3 * 2 * 3.14159;
      applyMouthValue(Math.max(0, Math.sin(phase) * 0.6 + 0.1));
      mouthRaf = window.requestAnimationFrame(tick);
    }
    mouthRaf = window.requestAnimationFrame(tick);
  }

  function startMouthSync() { startMouthAnimation(0); }

  function stopMouthSync() {
    if (mouthRaf) { window.cancelAnimationFrame(mouthRaf); mouthRaf = null; }
    applyMouthValue(0);
  }

  // ============================================================
  // 音频流（MSE / AudioContext / FileReader 三重 fallback）
  // ============================================================

  function setupAudioStreaming() {
    useMse = false;
    sourceQueue = [];
    fallbackChunks = [];
    sourceBuffer = null;
    if (mediaSourceUrl) {
      try { window.URL.revokeObjectURL(mediaSourceUrl); } catch (e) {}
      mediaSourceUrl = null;
    }
    if (!window.MediaSource || !window.MediaSource.isTypeSupported("audio/mpeg")) { return; }
    mediaSource = new window.MediaSource();
    mediaSourceUrl = window.URL.createObjectURL(mediaSource);
    audioPlayer.src = mediaSourceUrl;
    mediaSource.addEventListener("sourceopen", function () {
      try {
        sourceBuffer = mediaSource.addSourceBuffer("audio/mpeg");
        sourceBuffer.mode = "sequence";
        useMse = true;
        sourceBuffer.addEventListener("updateend", flushSourceQueue);
      } catch (err) {
        useMse = false;
        appendLog("WARN", "MSE 初始化失败，回退到缓存播放。");
      }
    });
  }

  function flushSourceQueue() {
    if (!sourceBuffer || sourceBuffer.updating || !sourceQueue.length) { return; }
    try { sourceBuffer.appendBuffer(sourceQueue.shift()); } catch (e) {
      appendLog("WARN", "MSE appendBuffer 失败: " + String(e));
      useMse = false; // 降级，下次用 fallback
    }
  }

  function base64ToUint8(b64) {
    var bin = window.atob(b64);
    var bytes = new Uint8Array(bin.length);
    var i;
    for (i = 0; i < bin.length; i += 1) { bytes[i] = bin.charCodeAt(i); }
    return bytes;
  }

  function onAudioChunk(payload) {
    var chunk = payload.chunk_base64 || "";
    if (!chunk) { return; }
    var bytes = base64ToUint8(chunk);
    if (useMse && sourceBuffer) {
      sourceQueue.push(bytes);
      flushSourceQueue();
      return;
    }
    fallbackChunks.push(bytes);
  }

  function onAudioEnd(payload) {
    var totalChunks = payload.total_chunks || 0;
    if (audioText) { audioText.textContent = "收到分片：" + totalChunks; }
    if (useMse) {
      // MSE 模式：重置 currentTime 到最新数据起始点，然后播放
      try { audioPlayer.currentTime = 0; } catch (e) {}
      playAudio();
      return;
    }
    if (!fallbackChunks.length) { return; }
    var totalLen = 0;
    var i;
    for (i = 0; i < fallbackChunks.length; i += 1) { totalLen += fallbackChunks[i].length; }
    var merged = new Uint8Array(totalLen);
    var offset = 0;
    for (i = 0; i < fallbackChunks.length; i += 1) {
      merged.set(fallbackChunks[i], offset);
      offset += fallbackChunks[i].length;
    }
    fallbackChunks = [];

    var Ctx = window.AudioContext || window.webkitAudioContext;
    if (Ctx) {
      if (!audioCtx) { audioCtx = new Ctx(); }
      audioCtx.decodeAudioData(merged.buffer.slice(0), function (decoded) {
        var src = audioCtx.createBufferSource();
        src.buffer = decoded;
        src.connect(audioCtx.destination);
        src.onended = stopMouthSync;
        src.start(0);
        startMouthAnimation(Math.ceil(decoded.duration * 1000));
        appendLog("INFO", "Web Audio 播放，时长 " + decoded.duration.toFixed(1) + "s");
      }, function (err) {
        appendLog("ERROR", "Web Audio 解码失败: " + String(err));
        playWithFileReader(merged);
      });
    } else {
      playWithFileReader(merged);
    }
  }

  function playWithFileReader(merged) {
    var blob = new Blob([merged], { type: "audio/mpeg" });
    var reader = new FileReader();
    reader.onload = function () { audioPlayer.src = reader.result; playAudio(); };
    reader.onerror = function () { appendLog("ERROR", "FileReader 音频读取失败。"); };
    reader.readAsDataURL(blob);
  }

  // ============================================================
  // WebSocket 消息处理
  // ============================================================

  function onMessage(raw) {
    var data = null;
    try { data = JSON.parse(raw.data); } catch (e) { appendLog("RECV_RAW", raw.data); return; }
    appendLog("RECV " + data.type, data);

    var t = String(data.type || "").toUpperCase();
    var payload = data.payload || {};

    // TEXT：AI 回复文字（含镜像来的小智回复）
    if (t === "TEXT") {
      var txt = payload.text || "";
      // 区分来源：小智 bridge 推送时 payload 可能含 source 标记，否则视为本 AI
      var role = payload.source === "xiaozhi" ? "xiaozhi" : "ai";
      addMessage(role, txt);
      if (effectText) { effectText.textContent = txt; }
      return;
    }
    if (t === "QRCODE") { renderQRCode(payload); return; }
    if (t === "AUDIO_URL") { renderAudio(payload); return; }
    if (t === "AUDIO_CHUNK") { onAudioChunk(payload); return; }
    if (t === "AUDIO_END") { onAudioEnd(payload); return; }
    if (t === "WEATHER_CARD") { renderWeatherOverlay(payload); return; }
    if (t === "ASR_RESULT") {
      var asrTxt = payload.text || "";
      if (asrTxt) { addMessage("user", asrTxt); }
      if (effectText) { effectText.textContent = "语音识别：" + asrTxt; }
      return;
    }
    if (t === "MODEL_SWITCH") { loadModel(payload.model_id || "default", payload.style || ""); return; }
    if (t === "EFFECT") {
      if (effectText) { effectText.textContent = "特效：" + (payload.action || ""); }
      if (String(payload.action || "").toUpperCase() === "HEART") { playHeartEffect(); }
      return;
    }
    if (t === "ERROR") {
      var errMsg = "错误：" + (payload.message || "未知错误");
      addMessage("system", errMsg);
      if (effectText) { effectText.textContent = errMsg; }
    }
  }

  // ============================================================
  // WebSocket 连接管理
  // ============================================================

  function connect() {
    var wsUrl = wsUrlInput ? wsUrlInput.value.trim() : "";
    if (!wsUrl) { appendLog("WARN", "WebSocket 地址为空，无法连接。"); return; }
    if (socket) { socket.close(); }
    setupAudioStreaming();
    setStatus("连接中...", "connecting");
    socket = new WebSocket(wsUrl);

    socket.onopen = function () {
      isConnected = true;
      setStatus("已连接", "connected");
      appendLog("INFO", "WebSocket 连接成功");
      addMessage("system", "已连接 AI 助手");
      if (tokenInput && tokenInput.value) {
        safeSend("AUTH", { token: tokenInput.value }, traceId("auth"));
      }
      if (pingTimer) { clearInterval(pingTimer); }
      pingTimer = setInterval(function () {
        safeSend("PING", {}, traceId("heartbeat"));
      }, 20000);
    };

    socket.onmessage = onMessage;
    socket.onerror = function () { appendLog("ERROR", "WebSocket 发生错误"); };
    socket.onclose = function () {
      isConnected = false;
      setStatus("已断开", "disconnected");
      appendLog("INFO", "WebSocket 连接关闭");
      if (pingTimer) { clearInterval(pingTimer); pingTimer = null; }
      if (userRequestedDisconnect) { userRequestedDisconnect = false; return; }
      if (reconnectTimer) { clearTimeout(reconnectTimer); }
      reconnectTimer = setTimeout(function () {
        if (!isConnected) { connect(); }
      }, 3000);
    };
  }

  function disconnect() {
    userRequestedDisconnect = true;
    if (reconnectTimer) { clearTimeout(reconnectTimer); }
    if (socket) { socket.close(); socket = null; }
    if (pingTimer) { clearInterval(pingTimer); pingTimer = null; }
    isConnected = false;
    setStatus("已断开", "disconnected");
  }

  // ============================================================
  // 发送文本
  // ============================================================

  function sendTextCommand() {
    var text = textInput ? (textInput.value || "").trim() : "";
    if (!text) { appendLog("WARN", "请输入文本指令。"); return; }
    addMessage("user", text);      // 立即在聊天记录显示用户消息
    safeSend("TEXT", { text: text });
    if (textInput) { textInput.value = ""; }
  }

  // ============================================================
  // 发送音频文件
  // ============================================================

  function uint8ToBase64(bytes) {
    var CHUNK = 0x8000;
    var index = 0;
    var result = "";
    while (index < bytes.length) {
      var slice = bytes.subarray(index, Math.min(index + CHUNK, bytes.length));
      var i; var bin = "";
      for (i = 0; i < slice.length; i += 1) { bin += String.fromCharCode(slice[i]); }
      result += window.btoa(bin);
      index += CHUNK;
    }
    return result;
  }

  function sendAudioInput() {
    if (!audioFileInput || !audioFileInput.files || !audioFileInput.files.length) {
      appendLog("WARN", "请先选择音频文件。"); return;
    }
    var file = audioFileInput.files[0];
    var reader = new FileReader();
    var trace = traceId("audio");
    reader.onload = function () {
      var bytes = new Uint8Array(reader.result);
      var chunkSize = 32 * 1024;
      var total = Math.ceil(bytes.length / chunkSize);
      var i;
      for (i = 0; i < total; i += 1) {
        var part = bytes.subarray(i * chunkSize, Math.min((i + 1) * chunkSize, bytes.length));
        safeSend("AUDIO_INPUT_CHUNK", {
          chunk_index: i, chunk_base64: uint8ToBase64(part),
          file_name: file.name, mime_type: file.type || "application/octet-stream"
        }, trace);
      }
      safeSend("AUDIO_INPUT_END", { file_name: file.name, chunks: total }, trace);
      if (audioUploadText) { audioUploadText.textContent = "已发送分片：" + total; }
    };
    reader.onerror = function () { appendLog("ERROR", "读取音频文件失败。"); };
    reader.readAsArrayBuffer(file);
  }

  // ============================================================
  // Live2D
  // ============================================================

  function initLive2D() {
    if (typeof L2Dwidget === "undefined" || typeof L2Dwidget.init !== "function") {
      appendLog("WARN", "L2Dwidget 未加载");
      if (modelText) { modelText.textContent = "Live2D 不可用"; }
      return false;
    }
    return true;
  }

  function loadModel(modelId, styleText) {
    if (!initLive2D()) { return; }
    var url = MODEL_URLS[modelId] || MODEL_URLS["default"];
    appendLog("INFO", "加载 Live2D: " + url);
    try {
      L2Dwidget.init({
        pluginRootPath: "./", pluginJsPath: "js/", pluginModelPath: "assets/",
        model: { jsonPath: url, scale: 1 },
        display: { position: "left", width: 180, height: 240, hOffset: 0, vOffset: 0 },
        mobile: { show: true, scale: 0.8 },
        react: { opacityDefault: 0.9, opacityOnHover: 0.2 }
      });
      live2dLoaded = true;
      if (modelText) { modelText.textContent = modelId + "（" + (styleText || "默认") + "）"; }
      appendLog("INFO", "L2Dwidget 初始化成功");
    } catch (e) {
      appendLog("ERROR", "L2Dwidget 异常: " + String(e));
    }
  }

  // Live2D 人物重定位：将 L2Dwidget 创建的浮动层移入容器
  function relocateLive2DWidget() {
    var widget = document.getElementById("live2d-widget");
    if (!widget) { setTimeout(relocateLive2DWidget, 600); return; }
    if (live2dContainer && widget.parentNode !== live2dContainer) {
      widget.style.position = "absolute";
      widget.style.bottom = "0";
      widget.style.left = "0";
      widget.style.right = "0";
      widget.style.margin = "0 auto";
      widget.style.top = "auto";
      live2dContainer.style.position = "relative";
      live2dContainer.appendChild(widget);
      appendLog("INFO", "Live2D 已嵌入容器");
    }
  }

  // ============================================================
  // 事件绑定
  // ============================================================

  if (connectBtn)    { connectBtn.onclick    = connect; }
  if (disconnectBtn) { disconnectBtn.onclick = disconnect; }
  if (sendTextBtn)   { sendTextBtn.onclick   = sendTextCommand; }
  if (sendAudioBtn)  { sendAudioBtn.onclick  = sendAudioInput; }
  if (textInput) {
    textInput.onkeydown = function (e) {
      if ((e.keyCode || e.which) === 13) { sendTextCommand(); }
    };
  }

  // 音频事件：口型 + 音频结束后重置 MSE，确保下一次 TTS 正常播放（修复 Issue 2）
  audioPlayer.addEventListener("play",   startMouthSync);
  audioPlayer.addEventListener("pause",  stopMouthSync);
  audioPlayer.addEventListener("ended",  function () {
    stopMouthSync();
    // 延迟 200ms 重置 MSE，为下一条 AI 回复的音频准备干净的 sourceBuffer
    setTimeout(setupAudioStreaming, 200);
  });

  // ============================================================
  // 启动序列
  // ============================================================

  setStatus("未连接", "disconnected");

  var autoHostname = window.location.hostname || "192.168.1.6";
  var autoWsUrl = "ws://" + autoHostname + ":8765";
  if (wsUrlInput) { wsUrlInput.value = autoWsUrl; }

  appendLog("DIAG", [
    "JS版本: v20260405a",
    "L2Dwidget: " + typeof L2Dwidget,
    "FileReader: " + typeof window.FileReader,
    "AudioContext: " + typeof (window.AudioContext || window.webkitAudioContext),
    "SpeechAPI: " + typeof (window.SpeechRecognition || window.webkitSpeechRecognition),
    "MediaSource: " + typeof window.MediaSource,
    "WS: " + autoWsUrl,
    "UA: " + navigator.userAgent.slice(0, 60)
  ].join(" | "));

  initVoiceInput();
  initLive2D();
  loadModel("default", "默认");

  setTimeout(function () {
    appendLog("INFO", "自动连接: " + autoWsUrl);
    connect();
  }, 1500);

  setTimeout(relocateLive2DWidget, 800);

})();
