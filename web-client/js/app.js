(function () {
  var socket = null;
  var isConnected = false;
  var reconnectTimer = null;
  var pingTimer = null;

  // ---- DOM 引用 ----
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
  var weatherText    = document.getElementById("weatherText");
  var weatherSection = document.getElementById("weatherSection");
  var weatherCards   = document.getElementById("weatherCards");
  var live2dContainer= document.getElementById("live2dContainer");
  var modelText      = document.getElementById("modelText");
  var mouthBarInner  = document.getElementById("mouthBarInner");
  var aiReplyText    = document.getElementById("aiReplyText");

  // 设置面板相关 DOM
  var settingsBtn      = document.getElementById("settingsBtn");
  var settingsPanel    = document.getElementById("settingsPanel");
  var settingsCloseBtn = document.getElementById("settingsCloseBtn");

  // 语音输入相关 DOM
  var voiceBtn = document.getElementById("voiceBtn");

  // ---- Live2D / 音频流状态变量 ----
  var live2dLoaded     = false;
  var audioCtx         = null;
  var analyser         = null;
  var analyserData     = null;
  var mouthRaf         = null;
  var mediaElementSource = null;

  var mediaSource    = null;
  var mediaSourceUrl = null;
  var sourceBuffer   = null;
  var sourceQueue    = [];
  var useMse         = false;
  var fallbackChunks = [];
  var userRequestedDisconnect = false;

  var MODEL_URLS = {
    "default": "./assets/models/shizuku/shizuku.model.json",
    "sport":   "./assets/models/shizuku/shizuku.model.json",
    "cute":    "./assets/models/shizuku/shizuku.model.json",
    "tech":    "./assets/models/shizuku/shizuku.model.json"
  };

  // ============================================================
  // 工具函数
  // ============================================================

  function nowTs() {
    return Math.floor(Date.now() / 1000);
  }

  function traceId(prefix) {
    return prefix + "-" + String(Date.now());
  }

  function appendLog(label, obj) {
    var text = "[" + new Date().toLocaleTimeString() + "] " + label + "\n";
    if (typeof obj === "string") {
      text += obj;
    } else {
      try {
        text += JSON.stringify(obj, null, 2);
      } catch (err) {
        text += String(obj);
      }
    }
    text += "\n\n";
    if (logBox) {
      logBox.textContent = text + logBox.textContent;
    }
  }

  function setStatus(text, dotClass) {
    if (statusText) {
      statusText.textContent = text;
    }
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
  // 设置面板开关
  // ============================================================

  function openSettings() {
    if (settingsPanel) {
      settingsPanel.className = settingsPanel.className.replace(" hidden", "").replace("hidden", "");
    }
  }

  function closeSettings() {
    if (settingsPanel) {
      if (settingsPanel.className.indexOf("hidden") === -1) {
        settingsPanel.className = settingsPanel.className + " hidden";
      }
    }
  }

  if (settingsBtn) {
    settingsBtn.onclick = openSettings;
  }
  if (settingsCloseBtn) {
    settingsCloseBtn.onclick = closeSettings;
  }

  // ============================================================
  // 语音输入（webkitSpeechRecognition / SpeechRecognition）
  // ============================================================

  var recognition = null;
  var isRecording = false;

  function initVoiceInput() {
    var SpeechAPI = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechAPI) {
      // 当前浏览器不支持语音识别，隐藏麦克风按钮
      if (voiceBtn) {
        voiceBtn.style.display = "none";
      }
      appendLog("WARN", "当前浏览器不支持语音识别（需要 Chrome / WebView 33+）");
      return;
    }

    recognition = new SpeechAPI();
    recognition.lang = "zh-CN";        // 识别语言：普通话
    recognition.continuous = false;    // 单次识别，说完即停
    recognition.interimResults = false;// 只取最终结果，不返回中间结果

    recognition.onstart = function () {
      isRecording = true;
      if (voiceBtn) {
        voiceBtn.className = "btn-voice recording";
      }
      appendLog("INFO", "语音识别已开启，请说话...");
    };

    recognition.onresult = function (event) {
      var transcript = "";
      if (event.results && event.results.length > 0) {
        transcript = event.results[0][0].transcript || "";
      }
      if (transcript && textInput) {
        textInput.value = transcript;
        appendLog("INFO", "语音识别结果: " + transcript);
        // 识别完成后自动发送
        sendTextCommand();
      }
    };

    recognition.onerror = function (e) {
      isRecording = false;
      if (voiceBtn) {
        voiceBtn.className = "btn-voice";
      }
      appendLog("WARN", "语音识别错误: " + (e.error || String(e)));
    };

    recognition.onend = function () {
      isRecording = false;
      if (voiceBtn) {
        voiceBtn.className = "btn-voice";
      }
    };

    if (voiceBtn) {
      voiceBtn.onclick = function () {
        if (isRecording) {
          // 再次点击停止
          recognition.stop();
        } else {
          try {
            recognition.start();
          } catch (err) {
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
    heartEffect.className = "heart-effect run";
    setTimeout(function () {
      heartEffect.className = "heart-effect hidden";
    }, 1100);
  }

  // ============================================================
  // QR码 / 音频 / 天气
  // ============================================================

  function renderQRCode(payload) {
    var qrimg = payload.qrimg || "";
    var qrurl = payload.qrurl || "";
    if (qrimg) {
      qrImage.src = qrimg;
      qrImage.className = "qr-image";
      qrText.textContent = qrurl ? "二维码链接：" + qrurl : "请扫码登录";
    } else if (qrurl) {
      qrImage.className = "qr-image hidden";
      qrText.textContent = "二维码链接：" + qrurl;
    } else {
      qrImage.className = "qr-image hidden";
      qrText.textContent = "二维码数据为空";
    }
  }

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
    if (!url) {
      audioText.textContent = "音频链接为空";
      return;
    }
    audioPlayer.src = url;
    audioText.textContent = "播放地址：" + url;
    playAudio();
  }

  function renderWeatherCard(payload) {
    var cityText = payload.city || "";
    var adm1 = payload.adm1 || "";
    var adm2 = payload.adm2 || "";
    var forecast = payload.forecast || [];
    if (weatherText) {
      weatherText.textContent = "城市：" + cityText + " " + adm1 + " " + adm2;
    }
    // 有天气数据时才显示天气区域
    if (weatherSection) {
      weatherSection.className = weatherSection.className.replace(" hidden", "").replace("hidden", "");
    }

    if (!weatherCards) { return; }
    while (weatherCards.firstChild) {
      weatherCards.removeChild(weatherCards.firstChild);
    }

    if (!forecast.length) {
      var empty = document.createElement("div");
      empty.className = "muted";
      empty.textContent = "天气数据为空";
      weatherCards.appendChild(empty);
      return;
    }

    var i = 0;
    for (i = 0; i < forecast.length; i += 1) {
      var day = forecast[i];
      var card = document.createElement("div");
      card.className = "weather-card";
      var dateNode = document.createElement("div");
      dateNode.className = "weather-date";
      dateNode.textContent = day.date || "";
      var mainNode = document.createElement("div");
      mainNode.className = "weather-main";
      mainNode.textContent =
        (day.text_day || "") + " / " + (day.text_night || "") +
        "  " + (day.temp_min || "") + "~" + (day.temp_max || "") + "°C";
      var windNode = document.createElement("div");
      windNode.className = "muted";
      windNode.textContent = "风向：" + (day.wind_dir_day || "");
      card.appendChild(dateNode);
      card.appendChild(mainNode);
      card.appendChild(windNode);
      weatherCards.appendChild(card);
    }
  }

  // ============================================================
  // Live2D
  // ============================================================

  function initLive2D() {
    if (typeof L2Dwidget === "undefined" || typeof L2Dwidget.init !== "function") {
      appendLog("WARN", "L2Dwidget 未加载（L2Dwidget=" + typeof L2Dwidget + "）");
      if (modelText) { modelText.textContent = "Live2D 不可用：L2Dwidget 未能加载"; }
      return false;
    }
    return true;
  }

  function loadModel(modelId, styleText) {
    if (!initLive2D()) { return; }
    var url = MODEL_URLS[modelId] || MODEL_URLS["default"];
    appendLog("INFO", "开始加载 Live2D 模型: " + url);
    try {
      L2Dwidget.init({
        pluginRootPath: "./",
        pluginJsPath: "js/",
        pluginModelPath: "assets/",
        model: {
          jsonPath: url,
          scale: 1
        },
        display: {
          position: "left",
          width: 180,
          height: 360,
          hOffset: 0,
          vOffset: 0
        },
        mobile: {
          show: true,
          scale: 0.8
        },
        react: {
          opacityDefault: 0.9,
          opacityOnHover: 0.2
        }
      });
      live2dLoaded = true;
      if (modelText) {
        modelText.textContent = "当前模型：" + modelId + "（" + (styleText || "默认") + "）";
      }
      appendLog("INFO", "L2Dwidget 初始化成功，模型加载中...");
    } catch (e) {
      appendLog("ERROR", "L2Dwidget 加载异常: " + String(e));
    }
  }

  // ============================================================
  // 口型动画
  // ============================================================

  function applyMouthValue(value) {
    var v = Math.max(0, Math.min(1, value));
    if (mouthBarInner) {
      mouthBarInner.style.width = String(Math.floor(v * 100)) + "%";
    }
    window._live2dMouthValue = v;
  }

  // 基于正弦波的口型动画，不依赖 analyser API，兼容旧 WebView
  function startMouthAnimation(durationMs) {
    stopMouthSync();
    var startTs = Date.now();
    function tick() {
      var elapsed = Date.now() - startTs;
      if (durationMs && elapsed >= durationMs) {
        applyMouthValue(0);
        mouthRaf = null;
        return;
      }
      var phase = elapsed / 1000 * 3 * 2 * 3.14159;
      var v = Math.max(0, Math.sin(phase) * 0.6 + 0.1);
      applyMouthValue(v);
      mouthRaf = window.requestAnimationFrame(tick);
    }
    mouthRaf = window.requestAnimationFrame(tick);
  }

  function startMouthSync() {
    startMouthAnimation(0);
  }

  function stopMouthSync() {
    if (mouthRaf) {
      window.cancelAnimationFrame(mouthRaf);
      mouthRaf = null;
    }
    applyMouthValue(0);
  }

  // ============================================================
  // 音频流（MSE / FileReader fallback）
  // ============================================================

  function setupAudioStreaming() {
    useMse = false;
    sourceQueue = [];
    fallbackChunks = [];
    sourceBuffer = null;
    if (mediaSourceUrl) {
      window.URL.revokeObjectURL(mediaSourceUrl);
      mediaSourceUrl = null;
    }
    if (!window.MediaSource || !window.MediaSource.isTypeSupported("audio/mpeg")) {
      return;
    }
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
    sourceBuffer.appendBuffer(sourceQueue.shift());
  }

  function base64ToUint8(base64Text) {
    var binary = window.atob(base64Text);
    var len = binary.length;
    var bytes = new Uint8Array(len);
    var i = 0;
    for (i = 0; i < len; i += 1) {
      bytes[i] = binary.charCodeAt(i);
    }
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
    if (audioText) { audioText.textContent = "收到语音分片：" + totalChunks; }
    if (useMse) {
      playAudio();
      return;
    }
    if (!fallbackChunks.length) { return; }
    var totalLen = 0;
    var i;
    for (i = 0; i < fallbackChunks.length; i += 1) {
      totalLen += fallbackChunks[i].length;
    }
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
      var buf = merged.buffer.slice(0);
      audioCtx.decodeAudioData(buf, function (decoded) {
        var src = audioCtx.createBufferSource();
        src.buffer = decoded;
        src.connect(audioCtx.destination);
        src.onended = function () { stopMouthSync(); };
        src.start(0);
        startMouthAnimation(Math.ceil(decoded.duration * 1000));
        if (audioText) {
          audioText.textContent = "Web Audio 播放中，时长 " + decoded.duration.toFixed(1) + "s";
        }
        appendLog("INFO", "Web Audio 解码成功，开始播放。");
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
    reader.onload = function () {
      audioPlayer.src = reader.result;
      playAudio();
    };
    reader.onerror = function () {
      appendLog("ERROR", "音频读取失败，FileReader 出错。");
    };
    reader.readAsDataURL(blob);
  }

  // ============================================================
  // WebSocket 消息处理
  // ============================================================

  function onMessage(raw) {
    var data = null;
    try {
      data = JSON.parse(raw.data);
    } catch (err) {
      appendLog("RECV_RAW", raw.data);
      return;
    }
    appendLog("RECV " + data.type, data);
    var t = String(data.type || "").toUpperCase();
    var payload = data.payload || {};

    if (t === "TEXT") {
      var replyTxt = payload.text || "";
      if (aiReplyText) { aiReplyText.textContent = replyTxt; }
      if (effectText)  { effectText.textContent = replyTxt; }
      return;
    }
    if (t === "QRCODE") {
      renderQRCode(payload);
      return;
    }
    if (t === "AUDIO_URL") {
      renderAudio(payload);
      return;
    }
    if (t === "AUDIO_CHUNK") {
      onAudioChunk(payload);
      return;
    }
    if (t === "AUDIO_END") {
      onAudioEnd(payload);
      return;
    }
    if (t === "WEATHER_CARD") {
      renderWeatherCard(payload);
      return;
    }
    if (t === "ASR_RESULT") {
      if (effectText) { effectText.textContent = "语音识别：" + (payload.text || ""); }
      return;
    }
    if (t === "MODEL_SWITCH") {
      loadModel(payload.model_id || "default", payload.style || "");
      return;
    }
    if (t === "EFFECT") {
      if (effectText) { effectText.textContent = "触发特效：" + (payload.action || ""); }
      if (String(payload.action || "").toUpperCase() === "HEART") {
        playHeartEffect();
      }
      return;
    }
    if (t === "ERROR") {
      if (effectText) { effectText.textContent = "服务端错误：" + (payload.message || "未知错误"); }
    }
  }

  // ============================================================
  // WebSocket 连接管理
  // ============================================================

  function connect() {
    var wsUrl = (wsUrlInput ? wsUrlInput.value : "").trim();
    if (!wsUrl) {
      appendLog("WARN", "WebSocket 地址为空，无法连接。");
      return;
    }
    if (socket) { socket.close(); }
    setupAudioStreaming();
    setStatus("连接中...", "connecting");
    socket = new WebSocket(wsUrl);

    socket.onopen = function () {
      isConnected = true;
      setStatus("已连接", "connected");
      appendLog("INFO", "WebSocket 连接成功");
      if (tokenInput && tokenInput.value) {
        safeSend("AUTH", { token: tokenInput.value }, traceId("auth"));
      }
      if (pingTimer) { clearInterval(pingTimer); }
      pingTimer = setInterval(function () {
        safeSend("PING", {}, traceId("heartbeat"));
      }, 20000);
    };

    socket.onmessage = onMessage;
    socket.onerror = function () {
      appendLog("ERROR", "WebSocket 发生错误");
    };
    socket.onclose = function () {
      isConnected = false;
      setStatus("已断开", "disconnected");
      appendLog("INFO", "WebSocket 连接关闭");
      if (pingTimer) {
        clearInterval(pingTimer);
        pingTimer = null;
      }
      if (userRequestedDisconnect) {
        userRequestedDisconnect = false;
        return;
      }
      if (reconnectTimer) { clearTimeout(reconnectTimer); }
      reconnectTimer = setTimeout(function () {
        if (!isConnected) { connect(); }
      }, 3000);
    };
  }

  function disconnect() {
    userRequestedDisconnect = true;
    if (reconnectTimer) { clearTimeout(reconnectTimer); }
    if (socket) {
      socket.close();
      socket = null;
    }
    if (pingTimer) {
      clearInterval(pingTimer);
      pingTimer = null;
    }
    isConnected = false;
    setStatus("已断开", "disconnected");
  }

  // ============================================================
  // 文本/音频发送
  // ============================================================

  function sendTextCommand() {
    var text = textInput ? (textInput.value || "").trim() : "";
    if (!text) {
      appendLog("WARN", "请输入文本指令。");
      return;
    }
    safeSend("TEXT", { text: text });
    if (textInput) { textInput.value = ""; }
  }

  function uint8ToBase64(bytes) {
    var CHUNK = 0x8000;
    var index = 0;
    var result = "";
    while (index < bytes.length) {
      var slice = bytes.subarray(index, Math.min(index + CHUNK, bytes.length));
      var i = 0;
      var bin = "";
      for (i = 0; i < slice.length; i += 1) {
        bin += String.fromCharCode(slice[i]);
      }
      result += window.btoa(bin);
      index += CHUNK;
    }
    return result;
  }

  function sendAudioInput() {
    if (!audioFileInput || !audioFileInput.files || !audioFileInput.files.length) {
      appendLog("WARN", "请先选择音频文件。");
      return;
    }
    var file = audioFileInput.files[0];
    var reader = new FileReader();
    var trace = traceId("audio");
    reader.onload = function () {
      var arrayBuffer = reader.result;
      var bytes = new Uint8Array(arrayBuffer);
      var chunkSize = 32 * 1024;
      var total = Math.ceil(bytes.length / chunkSize);
      var i = 0;
      for (i = 0; i < total; i += 1) {
        var start = i * chunkSize;
        var end = Math.min(start + chunkSize, bytes.length);
        var part = bytes.subarray(start, end);
        safeSend("AUDIO_INPUT_CHUNK", {
          chunk_index: i,
          chunk_base64: uint8ToBase64(part),
          file_name: file.name,
          mime_type: file.type || "application/octet-stream"
        }, trace);
      }
      safeSend("AUDIO_INPUT_END", { file_name: file.name, chunks: total }, trace);
      if (audioUploadText) {
        audioUploadText.textContent = "已发送音频分片：" + total + "，文件：" + file.name;
      }
    };
    reader.onerror = function () {
      appendLog("ERROR", "读取音频文件失败。");
    };
    reader.readAsArrayBuffer(file);
  }

  // ============================================================
  // 事件绑定
  // ============================================================

  if (connectBtn)    { connectBtn.onclick    = connect; }
  if (disconnectBtn) { disconnectBtn.onclick = disconnect; }
  if (sendTextBtn)   { sendTextBtn.onclick   = sendTextCommand; }
  if (sendAudioBtn)  { sendAudioBtn.onclick  = sendAudioInput; }
  if (textInput) {
    textInput.onkeydown = function (event) {
      var keyCode = event && (event.keyCode || event.which);
      if (keyCode === 13) { sendTextCommand(); }
    };
  }

  audioPlayer.addEventListener("play",   startMouthSync);
  audioPlayer.addEventListener("pause",  stopMouthSync);
  audioPlayer.addEventListener("ended",  stopMouthSync);

  // ============================================================
  // 启动序列
  // ============================================================

  setStatus("未连接", "disconnected");

  // 根据当前页面域名自动推断 WebSocket 地址
  var autoHostname = window.location.hostname || "192.168.1.6";
  var autoWsUrl = "ws://" + autoHostname + ":8765";
  if (wsUrlInput) { wsUrlInput.value = autoWsUrl; }

  appendLog("DIAG", [
    "JS版本: v20260404p",
    "L2Dwidget: " + typeof L2Dwidget,
    "FileReader: " + typeof window.FileReader,
    "AudioContext: " + typeof (window.AudioContext || window.webkitAudioContext),
    "SpeechAPI: " + typeof (window.SpeechRecognition || window.webkitSpeechRecognition),
    "自动WS地址: " + autoWsUrl,
    "UA: " + navigator.userAgent.slice(0, 60)
  ].join(" | "));

  initVoiceInput(); // 初始化语音识别
  initLive2D();
  loadModel("default", "默认");

  // 页面加载后延迟 1.5s 自动连接（等待 Live2D 初始化）
  setTimeout(function () {
    appendLog("INFO", "自动连接 WebSocket: " + autoWsUrl);
    connect();
  }, 1500);

  // Live2D 人物重定位：将 L2Dwidget 浮动层移入页面容器
  function relocateLive2DWidget() {
    var widget = document.getElementById("live2d-widget");
    if (!widget) {
      setTimeout(relocateLive2DWidget, 600);
      return;
    }
    if (live2dContainer && widget.parentNode !== live2dContainer) {
      widget.style.position = "absolute";
      widget.style.bottom = "0";
      widget.style.left = "0";
      widget.style.right = "0";
      widget.style.margin = "0 auto";
      widget.style.top = "auto";
      live2dContainer.style.position = "relative";
      live2dContainer.appendChild(widget);
      appendLog("INFO", "Live2D 人物已嵌入页面区域");
    }
  }
  setTimeout(relocateLive2DWidget, 800);

})();
