import { MINI_PROTOCOL_VERSION } from '../config/ws.js';

export const WS_STATUS = {
	DISCONNECTED: 'disconnected',
	CONNECTING: 'connecting',
	CONNECTED: 'connected',
	ERROR: 'error'
};

/**
 * 单连接封装：与 ppt_pc_client.py 接收的 JSON 格式一致。
 * - LASER：相对移动传 dx、dy（像素增量，PC 端再乘灵敏度）
 * - MOUSE_CLICK：传 button（如 left）、count（1 或 2）
 * - SEND_TEXT：传 text（字符串）
 * - SELECT_ALL：无额外字段
 * - SCREENSHOT：无额外字段（PC 保存截图；是否打开资源管理器由双方「截屏打开文件夹」开关决定）
 * - CLIENT_SETTINGS：screenshot_open_folder、transfer_open_folder、transfer_open_ppt、ppt_notes_enabled；可选 ppt_notes_text（PC 同步备注，与 PPT_NOTES 二选一即可）
 * - ONLINE / OFFLINE：服务端推送对端状态，须带 roomId（与当前连接 URL 中房间号一致才回调）
 * - CLIENT_SETTINGS：PC 端推送行为开关，须带 roomId；回调 setOnClientSettingsReceived
 * - PPT_NOTES：PC 端推送当前放映页备注 text（字符串）；须带 roomId；回调 setOnPptNotesReceived
 * - PC_WINDOW_MINIMIZE / PC_WINDOW_RESTORE：无额外字段（控制电脑端 Tk 主窗口最小化与恢复）
 * - SPOTLIGHT_SHOW / SPOTLIGHT_UPDATE：cx、cy、halfW、halfH（0–1 归一化；透光区为圆形，半径=min(halfW·屏宽,halfH·屏高)；外围半透明压暗）
 * - SPOTLIGHT_HIDE：关闭聚光灯遮罩
 * - TIMER_OVERLAY_SHOW：mode 为 countdown|stopwatch，seconds 为初始秒数
 * - TIMER_OVERLAY_PAUSE / TIMER_OVERLAY_RESUME / TIMER_OVERLAY_HIDE：无额外字段
 * - TIMER_OVERLAY_RESET：seconds（重置后的秒数）
 * - START_POWERPOINT / START_WPS_PPT：无额外字段（PC 启动 powerpnt.exe / wpp.exe）
 */

/**
 * 微信 onMessage 的 res.data 可能是 string 或 ArrayBuffer；后者直接 String 会破坏 JSON。
 */
function wsIncomingDataToString(data) {
	if (data == null || data === '') return '';
	if (typeof data === 'string') return data;
	try {
		let buf = data;
		if (buf && typeof buf.byteLength === 'number' && buf.byteLength >= 0) {
			if (typeof ArrayBuffer !== 'undefined' && buf instanceof ArrayBuffer) {
				buf = buf;
			} else if (buf.buffer && typeof buf.byteLength === 'number') {
				buf = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
			}
			const u8 = new Uint8Array(buf);
			if (typeof TextDecoder !== 'undefined') {
				return new TextDecoder('utf-8').decode(u8);
			}
			let s = '';
			for (let i = 0; i < u8.length; i++) {
				s += String.fromCharCode(u8[i]);
			}
			try {
				return decodeURIComponent(escape(s));
			} catch (e2) {
				return s;
			}
		}
	} catch (e) {
		// ignore
	}
	return String(data);
}

function extractRoomIdFromWsUrl(url) {
	try {
		const s = String(url || '').split('?')[0];
		const parts = s.split('/').filter(Boolean);
		if (!parts.length) return '';
		let last = parts[parts.length - 1];
		try {
			last = decodeURIComponent(last);
		} catch (e2) {
			// ignore
		}
		return String(last).trim().toUpperCase();
	} catch (e) {
		return '';
	}
}

export function createPptSocket() {
	let socketTask = null;
	let connId = 0;
	let status = WS_STATUS.DISCONNECTED;
	let lastError = '';
	let onStatus = null;
	let onPeerPresence = null;
	let onClientSettings = null;
	let onPptNotes = null;
	let onScreenshotDone = null;
	let onVersionMismatch = null;
	let expectedRoomId = '';

	function emit() {
		if (typeof onStatus === 'function') {
			onStatus(status, lastError);
		}
	}

	function setStatus(next, errMsg) {
		status = next;
		if (errMsg !== undefined) {
			lastError = errMsg || '';
		}
		emit();
	}

	function emitPeerOffline() {
		if (typeof onPeerPresence !== 'function') return;
		try {
			onPeerPresence({ online: false });
		} catch (e) {
			// ignore
		}
	}

	function connect(url) {
		const myId = ++connId;
		disconnect(false);
		expectedRoomId = extractRoomIdFromWsUrl(url);
		setStatus(WS_STATUS.CONNECTING, '');

		const task = uni.connectSocket({
			url,
			fail(err) {
				if (myId !== connId) return;
				lastError = err.errMsg || 'connectSocket 失败';
				setStatus(WS_STATUS.ERROR, lastError);
			}
		});

		socketTask = task && typeof task.onOpen === 'function' ? task : null;

		if (!socketTask) {
			lastError = '当前环境未返回 SocketTask，请升级微信基础库或使用真机';
			setStatus(WS_STATUS.ERROR, lastError);
			return;
		}

		socketTask.onOpen(() => {
			if (myId !== connId) return;
			emitPeerOffline();
			setStatus(WS_STATUS.CONNECTED, '');
			try {
				socketTask.send({
					data: JSON.stringify({ cmd: 'MINI_HELLO', version: MINI_PROTOCOL_VERSION }),
					fail: () => {}
				});
			} catch (e) {
				// ignore
			}
		});

		socketTask.onMessage((res) => {
			if (myId !== connId) return;
			let raw = res && res.data;
			if (raw == null) return;
			raw = wsIncomingDataToString(raw);
			if (!raw) return;
			try {
				const data = JSON.parse(raw);
				const cmd = data.cmd;
				const rid = String(data.roomId || '')
					.trim()
					.toUpperCase();
				if (cmd === 'CLIENT_SETTINGS') {
					if (!rid || !expectedRoomId || rid !== expectedRoomId) return;
					if (typeof onClientSettings === 'function') {
						const pt = data.ppt_notes_text;
						onClientSettings({
							screenshot_open_folder: data.screenshot_open_folder,
							transfer_open_folder: data.transfer_open_folder,
							transfer_open_ppt: data.transfer_open_ppt,
							ppt_notes_enabled: data.ppt_notes_enabled,
							ppt_notes_text: typeof pt === 'string' ? pt : undefined
						});
					}
					return;
				}
				if (cmd === 'PPT_NOTES') {
					if (!rid || !expectedRoomId || rid !== expectedRoomId) return;
					if (typeof onPptNotes === 'function') {
						const t = data.text;
						onPptNotes({ text: typeof t === 'string' ? t : t != null ? String(t) : '' });
					}
					return;
				}
				if (cmd === 'VERSION_MISMATCH') {
					if (typeof onVersionMismatch === 'function') {
						onVersionMismatch({ pcVersion: data.pc_version, minRequired: data.min_required });
					}
					return;
				}
				if (cmd === 'SCREENSHOT_DONE') {
					if (!rid || !expectedRoomId || rid !== expectedRoomId) return;
					if (typeof onScreenshotDone === 'function') {
						onScreenshotDone({ filename: data.filename || '' });
					}
					return;
				}
				if (cmd !== 'ONLINE' && cmd !== 'OFFLINE') return;
				if (!rid || !expectedRoomId || rid !== expectedRoomId) return;
				if (typeof onPeerPresence === 'function') {
					onPeerPresence({ online: cmd === 'ONLINE' });
				}
			} catch (e) {
				// ignore
			}
		});

		socketTask.onClose(() => {
			if (myId !== connId) return;
			socketTask = null;
			expectedRoomId = '';
			emitPeerOffline();
			setStatus(WS_STATUS.DISCONNECTED, '');
		});

		socketTask.onError((err) => {
			if (myId !== connId) return;
			lastError = (err && err.errMsg) || '连接错误';
			emitPeerOffline();
			setStatus(WS_STATUS.ERROR, lastError);
		});
	}

	/**
	 * @param {boolean} [notify=true] 是否触发 disconnected 状态回调
	 */
	function disconnect(notify = true) {
		if (socketTask) {
			try {
				socketTask.close({});
			} catch (e) {
				// ignore
			}
			socketTask = null;
		}
		expectedRoomId = '';
		emitPeerOffline();
		if (notify) {
			setStatus(WS_STATUS.DISCONNECTED, '');
		}
	}

	function sendCmd(cmd, opts = {}) {
		if (status !== WS_STATUS.CONNECTED || !socketTask) {
			return Promise.reject(new Error('未连接'));
		}
		const payload = JSON.stringify({ cmd, ...opts });
		return new Promise((resolve, reject) => {
			socketTask.send({
				data: payload,
				success: resolve,
				fail: (err) => reject(err || new Error('send 失败'))
			});
		});
	}

	function getStatus() {
		return status;
	}

	function getLastError() {
		return lastError;
	}

	function setOnStatusChange(cb) {
		onStatus = cb;
	}

	function setOnPeerPresence(cb) {
		onPeerPresence = typeof cb === 'function' ? cb : null;
	}

	function setOnClientSettingsReceived(cb) {
		onClientSettings = typeof cb === 'function' ? cb : null;
	}

	function setOnPptNotesReceived(cb) {
		onPptNotes = typeof cb === 'function' ? cb : null;
	}

	function setOnScreenshotDone(cb) {
		onScreenshotDone = typeof cb === 'function' ? cb : null;
	}

	function setOnVersionMismatch(cb) {
		onVersionMismatch = typeof cb === 'function' ? cb : null;
	}

	return {
		connect,
		disconnect,
		sendCmd,
		getStatus,
		getLastError,
		setOnStatusChange,
		setOnPeerPresence,
		setOnClientSettingsReceived,
		setOnPptNotesReceived,
		setOnScreenshotDone,
		setOnVersionMismatch,
		WS_STATUS
	};
}
