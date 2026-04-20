var Joy1;
var Joy2;
var Slider1;
var Slider2;

var shrew_task_timer;
var shrew_task_timer_backup;
var mixer_dirty = false;
var mixer_prev = "";
var wakeLock = null;

const CRSF_CHANNEL_VALUE_MIN  = 172;
const CRSF_CHANNEL_VALUE_1000 = 191;
const CRSF_CHANNEL_VALUE_MID  = 992;
const CRSF_CHANNEL_VALUE_2000 = 1792;
const CRSF_CHANNEL_VALUE_MAX  = 1811;

const channel = new Array(16).fill(CRSF_CHANNEL_VALUE_MID);
const channel16 = new Uint16Array(16);
const variable = new Array(32).fill(0);

function shrew_onLoad() {
    Joy1 = new JoyStick('joy1Div');
    Joy2 = new JoyStick('joy2Div');
    Slider1 = document.getElementById("slider_1");
    Slider2 = document.getElementById("slider_2");
    document.getElementById('joystick_area').classList.add("hidden");
    createDebugGrid();
    initWakeLock();
    setupGamepadEvents();
    configLoad(function () {
        websock_init();
        shrew_task_timer = requestAnimationFrame(shrew_task);
    });
}

function shrew_task()
{
    clearTimeout(shrew_task_timer_backup);
    var currentTime = Date.now();
    updateMixerFunction();
    if (MyGamepad == null) {
        updateGamepadState();
    } else {
        pollGamepad();
    }
    var tosend = false;
    try {
        let mixer_custom = mixer_prev;
        if (mixer_custom.trim().length <= 0) {
            if (MyGamepad == null) {
                mixer_custom = "return simpleTankMix({});";
            }
            else {
                mixer_custom = "return simpleTankMix({mode:4});";
            }
        }
        else if (mixer_custom.trim().endsWith("return true;") != true) {
            mixer_custom = "return false;";
        }
        let contents = "function mixer_run(){\r\n";
        contents += mixer_custom;
        contents += "\r\n}";
        eval(contents);
        if (typeof mixer_run === 'function') {
            tosend = mixer_run();
        }
    } catch (e) {
        console.error('error running mixer:', e);
    }
    fillDebugCells();
    if (ws_checkConnection() || ws.readyState === WebSocket.OPEN)
    {
        document.getElementById("msg_wifidisconnected").classList.add("hidden");
        if (ws.bufferedAmount === 0)
        {
            var timedout = ((currentTime - ws_timestamp) >= 100);
            if (timedout) {
                tosend = true;
            }
            if (typeof tosend === 'boolean' && tosend === true) {
                for (let i = 0; i < channel.length; i++) {
                    var x = clamp(channel[i], 0, 2048);
                    channel16[i] = Math.round(x);
                }
                var buffer = new ArrayBuffer((channel.length * 2) + 4);
                var dataview = new DataView(buffer);
                var headstr = gamepadIsDisconnected() ? "crsf" : "CRSF";
                for (let i = 0; i < headstr.length; i++) {
                    dataview.setUint8(i, headstr.charCodeAt(i));
                }
                channel16.forEach(function(x, idx) {
                    dataview.setUint16((idx * 2) + 4, x, true); // true for little-endian
                });
                ws.send(buffer);
            }
        }
    }
    else {
        document.getElementById("msg_wifidisconnected").classList.remove("hidden");
    }
    if (gamepadIsDisconnected()) {
        document.getElementById("msg_gamepaddisconnected").classList.remove("hidden");
    }
    else {
        document.getElementById("msg_gamepaddisconnected").classList.add("hidden");
    }
    shrew_task_timer = requestAnimationFrame(shrew_task);
    shrew_task_timer_backup = setTimeout(shrew_task, 100);
}

function updateMixerFunction() {
    var secondColumn = document.getElementById('second_column');
    var touchArea = document.getElementById('joystick_area');
    var gamepadArea = document.getElementById('gamepad_area');
    var nothing_shown = true;
    if (mixer_prev.includes("MyGamepad")) {
        gamepadArea.classList.remove('hidden');
        nothing_shown = false;
    }
    else {
        gamepadArea.classList.add('hidden');
    }
    if (mixer_prev.includes("Joy1") || mixer_prev.includes("Joy2")) {
        touchArea.classList.remove('hidden');
        nothing_shown = false;
    }
    else {
        touchArea.classList.add('hidden');
    }
    if (mixer_prev.includes("Joy2")) {
        secondColumn.classList.remove('hidden');
        nothing_shown = false;
    }
    else {
        secondColumn.classList.add('hidden');
    }
    if (nothing_shown)
    {
        if (MyGamepad != null) {
            gamepadArea.classList.remove('hidden');
        }
        else {
            touchArea.classList.remove('hidden');
        }
        mixer_dirty = true;
    }
}

var ws;
var ws_reconnect_timer = null;
var ws_timestamp = Date.now();
function websock_init() {
    ws_reconnect_timer = null;
    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const url = `${protocol}://${window.location.host}/shrew_ws`;
    console.log("Connecting WebSocket " + url);
    ws = new WebSocket(url);
    ws_timestamp = Date.now();
    var conn_timeout = setTimeout(function() {
        if (ws.readyState !== WebSocket.OPEN) {
            console.log('Connection timeout. Closing WebSocket.');
            ws.close();
            ws_primeReconnect();
        }
    }, 3000);
    ws.onopen = function() {
        clearTimeout(conn_timeout);
        ws_timestamp = Date.now();
        console.log('WebSocket connection established');
    };
    ws.onmessage = function(event) {
        ws_timestamp = Date.now();
        console.log('WebSocket data received:', event.data);
        if (typeof event.data === 'string' && event.data.startsWith("OK:")) {
            let telem = event.data.substring(3).split(',');
            let telemStr = `RSSI:&nbsp;${telem[0]}&nbsp;;&nbsp;LQ:&nbsp;${telem[1]}&nbsp;;&nbsp;SNR:&nbsp;${telem[2]}`;
            document.getElementById("msg_temeletry").innerHTML = telemStr;
            document.getElementById("msg_temeletry").classList.remove("hidden");
        }
        else if (typeof event.data === 'string' && event.data == "ok") {
            document.getElementById("msg_temeletry").classList.add("hidden");
        }
        else if (typeof event.data === 'string' && event.data == "bad") {
            document.getElementById("msg_nocontrol").classList.remove("hidden");
        }
    };
    ws.onclose = function(event) {
        console.log('WebSocket closed, event reason:', event.reason);
        ws_checkConnection();
        document.getElementById("msg_wifidisconnected").classList.remove("hidden");
    };
    ws.onerror = function(error) {
        console.error('WebSocket error: ' + error.code);
        ws_checkConnection();
    };
}

function ws_primeReconnect() {
    if (ws_reconnect_timer != null) {
        return;
    }
    clearTimeout(ws_reconnect_timer);
    ws_reconnect_timer = setTimeout(function() {
        ws_reconnect_timer = null;
        websock_init();
    }, 1000);
}

var timeout_cnt = 0;
function ws_checkConnection() {
    var currentTime = Date.now();
    var timedout = ((currentTime - ws_timestamp) >= 1000);
    if (ws.readyState !== WebSocket.OPEN) {
        return false;
    }
    else {
        if (timedout) {
            //console.log('WebSocket no response, closing');
            //ws.close();
            //ws_primeReconnect();
            return false;
        }
    }
    return ws.readyState === WebSocket.OPEN;
}

var final_funct = null;
var config_get_retry = 3;
function configLoad(f) {
    if (typeof f === 'function') {
        final_funct = f;
    }
    var xhr = new XMLHttpRequest();
    xhr.open('GET', "/shrewcfgload", true);
    xhr.onreadystatechange = function() {
        if (xhr.readyState === XMLHttpRequest.DONE) {
            if (xhr.status === 200) {
                try {
                    var jsonData = JSON.parse(xhr.responseText);
                    populateFormWithData(jsonData);
                } catch (e) {
                    console.error('Could not parse JSON data:', e);
                }
                if (typeof final_funct === 'function') {
                    final_funct();
                }
            } else {
                console.error('Request failed with status:', xhr.status);
                config_get_retry -= 1;
                if (config_get_retry > 0) {
                    setTimeout(configLoad, 1000);
                }
                else {
                    if (typeof final_funct === 'function') {
                        final_funct();
                    }
                }
            }
        }
    };
    xhr.send();
}

function configSave() {
  var formData = new FormData(document.getElementById('config_data_form'));
  let object = {};
  formData.forEach((value, key) => {
    if(object.hasOwnProperty(key)) {
      if(Array.isArray(object[key])) {
        object[key].push(value);
      } else {
        object[key] = [object[key], value];
      }
    } else {
      object[key] = value;
    }
  });
  let formJson = JSON.stringify(object);
  var xhr = new XMLHttpRequest();
  xhr.open('POST', '/shrewcfgsave', true);
  xhr.setRequestHeader("Content-Type", "application/json");
  xhr.onload = function () {
    if (xhr.status === 200) {
      console.log('btn_configSave: form submitted successfully');
    } else {
      console.error('btn_configSave: an error occurred, status: ' + xhr.status.toString());
    }
  };
  xhr.send(formJson);
}

document.getElementById('mixerFileInput').addEventListener('change', function() {
    if (this.value == '') {
        return;
    }
    var file = this.files[0];
    var reader = new FileReader();
    reader.onload = function() {
        document.getElementById('txt_mixer').value = this.result;
        document.getElementById('mixerFileInput').value = '';
    }
    reader.onerror = function() {
        console.log('Error occurred while reading the file:', reader.error);
    };
    reader.readAsText(file);
});

function configLoadLocal() {
    let text = document.getElementById('txt_mixer').value;
    let blob = new Blob([text], {type: 'text/plain'});
    let url = URL.createObjectURL(blob);
    let link = document.createElement('a');
    link.href = url;
    link.download = 'mixer-' + currentDateTimeStr() + ".txt";
    link.click();
}

function populateFormWithData(jsonData) {
    for (var key in jsonData) {
        if (jsonData.hasOwnProperty(key)) {
            var element = document.getElementById(key);
            if (element) {
                if (element.type === 'checkbox') {
                    element.checked = jsonData[key];
                } else {
                    element.value = jsonData[key];
                }
            }
        }
    }
    mixer_onChange();
}

function mixer_onChange() {
    var txtele = document.getElementById('txt_mixer');
    var newtxt = txtele.value;
    if (newtxt != mixer_prev) {
        mixer_dirty = true;
        mixer_prev = newtxt;
    }
}

function showHideConfig() {
    var div = document.getElementById('div_config');
    div.classList.toggle('hidden');
}

function showHideDebug() {
    var div = document.getElementById('debug_hider');
    div.classList.toggle('hidden');
}

var activeGamepadIndex = null;
var activeGamepadId = null;
var MyGamepad = null;
var PrevButton = [];
var OnButtonPress = null;

function updateGamepadState() {
    const gamepads = navigator.getGamepads ? navigator.getGamepads() : [];
    for (let i = 0; i < gamepads.length; i++) {
        const gamepad = gamepads[i];
        if (gamepad && activeGamepadIndex === null) {
            if (gamepad.buttons.some(button => button.pressed) || gamepad.axes.some(axis => Math.abs(axis) > 0.1)) {
                activeGamepadIndex = gamepad.index;
                console.log(`Active gamepad set to index ${activeGamepadIndex}`);
                MyGamepad = navigator.getGamepads()[activeGamepadIndex];
                if (activeGamepadId != MyGamepad.id) {
                    activeGamepadId = MyGamepad.id;
                    buildGamepadView();
                }
                PrevButton = new Array(MyGamepad.buttons.length).fill(false);
            }
        }
    }
}

function buildGamepadView() {
    document.getElementById('gamepad_id').innerHTML = "Gamepad: " + MyGamepad.id;
    var container = document.getElementById('gamepad_buttons');
    container.innerHTML = "";
    for (let i = 0; i < MyGamepad.buttons.length; i++) {
        const square = document.createElement('span');
        square.classList.add('square');
        square.id = "sqr_btn_" + i;
        square.innerHTML = i.toString();
        container.appendChild(square);
    }
    container = document.getElementById('gamepad_axis');
    container.innerHTML = "";
    for (let i = 0; i < MyGamepad.axes.length; i++) {
        const square = document.createElement('span');
        square.classList.add('square');
        square.id = "sqr_axes_" + i;
        square.innerHTML = i.toString();
        container.appendChild(square);
    }
    pollGamepad();
}

function pollGamepad() {
    const gamepads = navigator.getGamepads ? navigator.getGamepads() : [];
    MyGamepad = gamepads[activeGamepadIndex];
    for (let i = 0; i < MyGamepad.buttons.length; i++) {
        var ele = document.getElementById("sqr_btn_" + i);
        if (MyGamepad.buttons[i].pressed) {
            var r = 127; var g = 127; var b = 127; var x = MyGamepad.buttons[i].value;
            r = mapRange(x, 0, 1, 127, 255, true);
            g = mapRange(x, 0, 1, 127, 0, true);
            b = g;
            ele.style.backgroundColor = `rgb(${r}, ${g}, ${b})`;
            ele.style.borderColor     = 'green';
        }
        else {
            ele.style.backgroundColor = 'gray';
            ele.style.borderColor     = 'black';
        }
        if (PrevButton.length > i ) {
            if (MyGamepad.buttons[i].pressed && PrevButton[i] != true && typeof OnButtonPress === 'function') {
                OnButtonPress(i);
            }
            PrevButton[i] = MyGamepad.buttons[i].pressed;
        }
    }
    for (let i = 0; i < MyGamepad.axes.length; i++) {
        var ele = document.getElementById("sqr_axes_" + i);
        var x = MyGamepad.axes[i];
        var r = 0; var g = 0; var b = 0;
        if (x < 0) {
            b = mapRange(x, -1, 0, 255, 0, true);
            ele.style.backgroundColor = `rgb(${r}, ${g}, ${b})`;
            //ele.style.borderColor     = 'rgb(32, 32, 32)';
        }
        else {
            r = mapRange(x, 0, 1, 0, 255, true);
            ele.style.backgroundColor = `rgb(${r}, ${g}, ${b})`;
            //ele.style.borderColor     = 'rgb(223, 223, 223)';
        }
        ele.style.borderColor = 'rgb(32, 32, 32)';
    }
}

function setupGamepadEvents() {
    window.addEventListener('gamepadconnected', (event) => {
        console.log(`Gamepad connected at index ${event.gamepad.index}: ${event.gamepad.id}.`);
        updateGamepadState();
    });
    
    window.addEventListener('gamepaddisconnected', (event) => {
        console.log(`Gamepad disconnected from index ${event.gamepad.index}: ${event.gamepad.id}`);
        if (activeGamepadIndex === event.gamepad.index) {
            activeGamepadIndex = null;
            MyGamepad = null;
            console.log('Active gamepad has been disconnected.');
        }
        updateGamepadState();
    });
}

function gamepadIsDisconnected() {
    if (MyGamepad == null && activeGamepadId != null) {
        return true;
    }
    return false;
}

function createDebugGrid() {
    const container = document.getElementById('debug_area');
    container.style.display = 'grid';
    container.style.gridTemplateColumns = ` 1fr 2fr 1fr 2fr`;
    container.style.width = '100%';
    var ch = 0; var vr = 0;

    for (let row = 0; ch < channel.length || vr < variable.length; row++) {
        for (let col = 0; col < 4; col++) {
            const cell = document.createElement('div');
            cell.classList.add('dbggrid-cell');
            if (col == 0 || col == 2) {
                cell.classList.add('right-aligned');
                if (ch < 16) {
                    cell.innerHTML = "Ch " + (ch + 0).toString() + ":";
                    cell.id = `dbgcell_ch_lbl_${ch}`;
                }
                else {
                    cell.innerHTML = "Var " + (vr).toString() + ":";
                    cell.id = `dbgcell_var_lbl_${vr}`;
                }
            }
            else if (col == 1 || col == 3) {
                cell.innerHTML = "&nbsp;";
                if (ch < channel.length) {
                    cell.id = `dbgcell_ch_val_${ch}`;
                    ch += 1;
                }
                else {
                    cell.id = `dbgcell_var_val_${vr}`;
                    vr += 1;
                }
            }
            container.appendChild(cell);
        }
    }
}

function fillDebugCells() {
    for (let i = 0; i < channel.length; i++) {
        var cell = document.getElementById(`dbgcell_ch_val_${i}`);
        cell.innerHTML = channel[i].toFixed(1);
    }
    for (let i = 0; i < variable.length; i++) {
        var cell = document.getElementById(`dbgcell_var_val_${i}`);
        cell.innerHTML = variable[i].toFixed(1);
    }
}

function initWakeLock() {
    const requestWakeLock = async () => {
        try {
            wakeLock = await navigator.wakeLock.request('screen');
            console.log('Screen wake lock is active');
            wakeLock.addEventListener('release', () => {
                console.log('Screen wake lock was released');
            });
        } catch (err) {
            console.error(`${err.name}, ${err.message}`);
        }
        try {
            //const anyNav: any = navigator;
            if ('wakeLock' in navigator) {
                navigator["wakeLock"].request("screen")
            }
        } catch (err) {
            console.error(`${err.name}, ${err.message}`);
        }
    };
    document.addEventListener('visibilitychange', async () => {
        if (wakeLock !== null && document.visibilityState === 'visible') {
            await requestWakeLock();
        }
    });
    requestWakeLock();
}

function currentDateTimeStr() {
    let now     = new Date();
    let year    = now.getFullYear();
    let month   = ("0" + (now.getMonth() + 1)).slice(-2);
    let day     = ("0" + now.getDate()).slice(-2);
    let hours   = ("0" + now.getHours()).slice(-2);
    let minutes = ("0" + now.getMinutes()).slice(-2);
    let seconds = ("0" + now.getSeconds()).slice(-2);
    return year + month + day + hours + minutes + seconds;
}

function clamp(value, limit1, limit2) {
    var min = Math.min(limit1, limit2);
    var max = Math.max(limit1, limit2);
    return Math.min(Math.max(value, min), max);
}

function mapRange(value, low1, high1, low2, high2, limit) {
    var x = low2 + (high2 - low2) * (value - low1) / (high1 - low1);
    if (limit) {
        x = clamp(x, low2, high2);
    }
    return x;
}

function applyDeadzone(x, dz) {
    if (dz >= 0)
    {
        if (x < dz && x > dz) {
            return 0;
        }
        else if (x >= 0) {
            return mapRange(x, dz, 1, 0, 1, true);
        }
        else {
            return mapRange(x, -dz, -1, 0, -1, true);
        }
    }
    else
    {
        dz = -dz;
        if (x > 0 && x != 0) {
            return mapRange(x, 0, 1, dz, 1, true);
        }
        else if (x < 0 && x != 0) {
            return mapRange(x, -1, 0, -1, -dz, true);
        }
        else {
            return 0;
        }
    }
}

function applyExpo(x, ex) {
    var absx = Math.abs(x);
    var absy = absx * Math.exp(ex * (absx - 1));
    return absy * ((x >= 0) ? 1 : -1);
}

function scaleToCRSF(x, s) {
    return mapRange(x * s, -1, 1, CRSF_CHANNEL_VALUE_MIN, CRSF_CHANNEL_VALUE_MAX, true);
}

function sliderToCRSF(x, s) {
    return mapRange(x * s, 0, 100, CRSF_CHANNEL_VALUE_MIN, CRSF_CHANNEL_VALUE_MAX, true);
}

function arcadeTankMix(t, s) {
    // 1. Get X and Y from the Joystick, do whatever scaling and calibrating you need to do based on your hardware.
    // 2. Invert X
    // 3. Calculate R+L (Call it V): V = (100-ABS(X)) * (Y/100) + Y
    // 4. Calculate R-L (Call it W): W = (100-ABS(Y)) * (X/100) + X
    // 5. Calculate R: R = (V+W) / 2
    // 6. Calculate L: L = (V-W) / 2
    // 7. Do any scaling on R and L your hardware may require.
    // 8. Send those values to your Robot.
    // 9. Go back to 1.

    let invs = -s;
    let v = ((1 - Math.abs(s)) * t) + t;
    let w = ((1 - Math.abs(t)) * invs) + invs;
    let r = (v + w) / 2;
    let l = (v - w) / 2;
    return [clamp(l, -1, 1), clamp(r, -1, 1)];
}

function simpleTankMix({mode = 0, thr_scale = 1, str_scale = 1, thr_dz = 0.05, str_dz = 0.05, thr_exp = 0, str_exp = 0, thr_trim = 0, str_trim = 0, left_scale = 1, right_scale = 1, left_dz = 0, right_dz = 0, left_exp = 0, right_exp = 0, left_trim = 0, right_trim = 0, chan_offset = 0}) {
    let ret = true;
    let t = 0;
    let s = 0;
    if (typeof mode === 'function') {
        let ts = mode();
        t = ts[0];
        s = ts[1];
    }
    else if (mode == 0) {
        t = Joy1.GetY();
        s = Joy1.GetX();
    }
    else if (mode == 1) {
        t = Joy1.GetY();
        s = Joy2.GetX();
    }
    else if (mode == 2) {
        t = Joy2.GetY();
        s = Joy1.GetX();
    }
    else
    {
        if (MyGamepad == null) {
            ret = false;
        }
        else if (mode == 3) {
            t = -MyGamepad.axes[1];
            s = MyGamepad.axes[0];
        }
        else if (mode == 4) {
            t = -MyGamepad.axes[3];
            s = MyGamepad.axes[2];
        }
        else if (mode == 5) {
            t = -MyGamepad.axes[1];
            s = MyGamepad.axes[2];
        }
        else if (mode == 6) {
            t = -MyGamepad.axes[3];
            s = MyGamepad.axes[0];
        }
        else if (mode == 7) {
            t = MyGamepad.buttons[7].value - MyGamepad.buttons[6].value;
            s = (Math.abs(MyGamepad.axes[0]) > Math.abs(MyGamepad.axes[2])) ? MyGamepad.axes[0] : MyGamepad.axes[2];
        }
        else if (mode == 8) {
            t = MyGamepad.buttons[6].value - MyGamepad.buttons[7].value;
            s = (Math.abs(MyGamepad.axes[0]) > Math.abs(MyGamepad.axes[2])) ? MyGamepad.axes[0] : MyGamepad.axes[2];
        }
    }
    t += thr_trim;
    s += str_trim;
    t = applyDeadzone(t, thr_dz);
    s = applyDeadzone(s, str_dz);
    t = applyExpo(t, thr_exp);
    s = applyExpo(s, str_exp);
    t *= thr_scale;
    s *= str_scale;
    let lr = arcadeTankMix(t, s); 
    lr[0] = applyExpo(lr[0], left_exp)
    lr[1] = applyExpo(lr[1], right_exp)
    lr[0] = applyDeadzone(lr[0], left_dz)
    lr[1] = applyDeadzone(lr[1], right_dz)
    channel[0 + chan_offset] = scaleToCRSF(lr[0] + left_trim, left_scale);
    channel[1 + chan_offset] = scaleToCRSF(lr[1] + right_trim, right_scale);
    return ret;
}
