(function () {
  var socket = null;
  var isConnected = false;
  var reconnectTimer = null;
  var pingTimer = null;

  var wsUrlInput = document.getElementById("wsUrlInput");
  var tokenInput = document.getElementById("tokenInput");
  var connectBtn = document.getElementById("connectBtn");
  var disconnectBtn = document.getElementById("disconnectBtn");
  var sendTextBtn = document.getElementById("sendTextBtn");
  var statusText = document.getElementById("statusText");
  var textInput = document.getElementById("textInput");
  var logBox = document.getElementById("logBox");
  var qrText = document.getElementById("qrText");
  var qrImage = document.getElementById("qrImage");
  var audioPlayer = document.getElementById("audioPlayer");
  var audioText = document.getElementById("audioText");
  var effectText = document.getElementById("effectText");
  var heartEffect = document.getElementById("heartEffect");
  var weatherText = document.getElementById("weatherText");
  var weatherCards = document.getElementById("weatherCards");
  var live2dContainer = document.getElementById("live2dContainer");
  var modelText = document.getElementById("modelText");
  var mouthBarInner = document.getElementById("mouthBarInner");

  var live2dApp = null;
  var currentModel = null;
  var audioCtx = null;
  var analyser = null;
  var analyserData = null;
  var mouthRaf = null;
  var mediaElementSource = null;

  var mediaSource = null;
  var sourceBuffer = null;
  var sourceQueue = [];
  var useMse = false;
  var fallbackChunks = [];

  var MODEL_URLS = {
    default: "https://cdn.jsdelivr.net/gh/guansss/pixi-live2d-display/test/assets/haru/haru.model3.json",
    sport: "https://cdn.jsdelivr.net/gh/guansss/pixi-live2d-display/test/assets/hiyori_pro_t10/hiyori_pro_t10.model3.json",
    cute: "https://cdn.jsdelivr.net/gh/guansss/pixi-live2d-display/test/assets/shizuku/shizuku.model.json",
    tech: "https://cdn.jsdelivr.net/gh/guansss/pixi-live2d-display/test/assets/epsilon2.1/Epsilon2.1.model.json"
  };

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
    logBox.textContent = text + logBox.textContent;
  }

  function setStatus(text) {
    statusText.textContent = "状态：" + text;
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

  function playHeartEffect() {
    heartEffect.className = "heart-effect run";
    setTimeout(function () {
      heartEffect.className = "heart-effect hidden";
    }, 1100);
  }

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
    audioPlayer.play()["catch"](function () {
      appendLog("WARN", "浏览器阻止了自动播放，请手动点击播放按钮。");
    });
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
    weatherText.textContent = "城市：" + cityText + " " + adm1 + " " + adm2;

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
        (day.text_day || "") + " / " + (day.text_night || "") + "  " + (day.temp_min || "") + "~" + (day.temp_max || "") + "°C";
      var windNode = document.createElement("div");
      windNode.className = "muted";
      windNode.textContent = "风向：" + (day.wind_dir_day || "");
      card.appendChild(dateNode);
      card.appendChild(mainNode);
      card.appendChild(windNode);
      weatherCards.appendChild(card);
    }
  }

  function initLive2D() {
    if (!window.PIXI || !live2dContainer) {
      appendLog("WARN", "PIXI 未加载，Live2D 功能不可用。");
      return;
    }
    if (live2dApp) {
      return;
    }
    live2dApp = new window.PIXI.Application({
      width: live2dContainer.clientWidth || 640,
      height: 320,
      backgroundColor: 0x0d1118,
      antialias: true
    });
    live2dContainer.appendChild(live2dApp.view);
  }

  function loadModel(modelId, styleText) {
    initLive2D();
    if (!live2dApp) {
      return;
    }
    if (!window.PIXI.Live2DModel || !window.PIXI.Live2DModel.from) {
      appendLog("WARN", "Live2DModel 库未就绪，无法加载模型。");
      return;
    }

    var url = MODEL_URLS[modelId] || MODEL_URLS.default;
    window.PIXI.Live2DModel.from(url)
      .then(function (model) {
        if (currentModel) {
          live2dApp.stage.removeChild(currentModel);
        }
        currentModel = model;
        model.scale.set(0.18);
        model.x = live2dApp.renderer.width * 0.5;
        model.y = live2dApp.renderer.height * 0.95;
        model.anchor.set(0.5, 1);
        live2dApp.stage.addChild(model);
        modelText.textContent = "当前模型：" + modelId + "（" + (styleText || "默认") + "）";
      })
      ["catch"](function (err) {
        appendLog("ERROR", "模型加载失败: " + String(err));
      });
  }

  function applyMouthValue(value) {
    var v = Math.max(0, Math.min(1, value));
    mouthBarInner.style.width = String(Math.floor(v * 100)) + "%";
    if (!currentModel || !currentModel.internalModel || !currentModel.internalModel.coreModel) {
      return;
    }
    var coreModel = currentModel.internalModel.coreModel;
    if (coreModel.setParameterValueById) {
      coreModel.setParameterValueById("ParamMouthOpenY", v);
    }
  }

  function startMouthSync() {
    if (!window.AudioContext && !window.webkitAudioContext) {
      return;
    }
    if (!audioCtx) {
      var Ctx = window.AudioContext || window.webkitAudioContext;
      audioCtx = new Ctx();
    }
    if (!mediaElementSource) {
      mediaElementSource = audioCtx.createMediaElementSource(audioPlayer);
      analyser = audioCtx.createAnalyser();
      analyser.fftSize = 512;
      analyserData = new Uint8Array(analyser.frequencyBinCount);
      mediaElementSource.connect(analyser);
      analyser.connect(audioCtx.destination);
    }
    function tick() {
      if (!analyser) {
        return;
      }
      analyser.getByteFrequencyData(analyserData);
      var sum = 0;
      var i = 0;
      for (i = 0; i < analyserData.length; i += 1) {
        sum += analyserData[i];
      }
      var level = sum / analyserData.length / 255;
      applyMouthValue(level);
      mouthRaf = window.requestAnimationFrame(tick);
    }
    if (!mouthRaf) {
      mouthRaf = window.requestAnimationFrame(tick);
    }
  }

  function stopMouthSync() {
    if (mouthRaf) {
      window.cancelAnimationFrame(mouthRaf);
      mouthRaf = null;
    }
    applyMouthValue(0);
  }

  function setupAudioStreaming() {
    useMse = false;
    sourceQueue = [];
    fallbackChunks = [];
    sourceBuffer = null;
    if (!window.MediaSource || !window.MediaSource.isTypeSupported("audio/mpeg")) {
      return;
    }
    mediaSource = new window.MediaSource();
    audioPlayer.src = window.URL.createObjectURL(mediaSource);
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
    if (!sourceBuffer || sourceBuffer.updating) {
      return;
    }
    if (!sourceQueue.length) {
      return;
    }
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
    if (!chunk) {
      return;
    }
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
    audioText.textContent = "收到语音分片：" + totalChunks;
    if (useMse) {
      playAudio();
      return;
    }
    if (!fallbackChunks.length) {
      return;
    }
    var blob = new Blob(fallbackChunks, { type: "audio/mpeg" });
    audioPlayer.src = window.URL.createObjectURL(blob);
    fallbackChunks = [];
    playAudio();
  }

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
      effectText.textContent = "AI回复：" + (payload.text || "");
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
    if (t === "MODEL_SWITCH") {
      loadModel(payload.model_id || "default", payload.style || "");
      return;
    }
    if (t === "EFFECT") {
      effectText.textContent = "触发特效：" + (payload.action || "");
      if (String(payload.action || "").toUpperCase() === "HEART") {
        playHeartEffect();
      }
      return;
    }
    if (t === "ERROR") {
      effectText.textContent = "服务端错误：" + (payload.message || "未知错误");
    }
  }

  function connect() {
    var wsUrl = wsUrlInput.value;
    if (!wsUrl) {
      appendLog("WARN", "请输入 WebSocket 地址。");
      return;
    }
    if (socket) {
      socket.close();
    }
    setupAudioStreaming();
    setStatus("连接中...");
    socket = new WebSocket(wsUrl);

    socket.onopen = function () {
      isConnected = true;
      setStatus("已连接");
      appendLog("INFO", "WebSocket 连接成功");
      if (tokenInput.value) {
        safeSend("AUTH", { token: tokenInput.value }, traceId("auth"));
      }
      if (pingTimer) {
        clearInterval(pingTimer);
      }
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
      setStatus("已断开");
      appendLog("INFO", "WebSocket 连接关闭");
      if (pingTimer) {
        clearInterval(pingTimer);
        pingTimer = null;
      }
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
      }
      reconnectTimer = setTimeout(function () {
        if (!isConnected) {
          connect();
        }
      }, 3000);
    };
  }

  function disconnect() {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
    }
    if (socket) {
      socket.close();
      socket = null;
    }
    if (pingTimer) {
      clearInterval(pingTimer);
      pingTimer = null;
    }
    isConnected = false;
    setStatus("已断开");
  }

  function sendTextCommand() {
    var text = (textInput.value || "").trim();
    if (!text) {
      appendLog("WARN", "请输入文本指令。");
      return;
    }
    safeSend("TEXT", { text: text });
  }

  connectBtn.onclick = connect;
  disconnectBtn.onclick = disconnect;
  sendTextBtn.onclick = sendTextCommand;
  textInput.onkeydown = function (event) {
    var keyCode = event && (event.keyCode || event.which);
    if (keyCode === 13) {
      sendTextCommand();
    }
  };
  audioPlayer.addEventListener("play", startMouthSync);
  audioPlayer.addEventListener("pause", stopMouthSync);
  audioPlayer.addEventListener("ended", stopMouthSync);

  setStatus("未连接");
  initLive2D();
  loadModel("default", "默认");
})();
