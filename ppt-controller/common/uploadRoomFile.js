import { buildFileUploadUrl } from '../config/ws.js';

import { STORAGE_PPT_ACTIVE_ROOM, STORAGE_PPT_WS_CONNECTED } from './pptSession.js';

import { ROOM_RE } from './roomCode.js';



/** 与 tabbar-4 / 清除缓存 共用，单文件避免 mp 端多 common 模块未注册 */

export const STORAGE_SEND_HISTORY = 'ppt_send_history';

export const STORAGE_USER_PROFILE = 'ppt_user_profile';

/** 发送记录 tab 角标：用户上次在记录页「已看到」的条数，用于 len > lastSeen 时显示角标 */
export const STORAGE_SEND_LAST_SEEN_LEN = 'ppt_send_last_seen_len';

/** 与 pages.json tabBar.list 一致：0 首页 1 常用排序 2 发送到PC 3 发送记录 */
export const TAB_BAR_SEND_RECORDS_INDEX = 3;

const MAX_SEND_RECORDS = 100;



function genSendRecordId() {

	return `${Date.now()}_${Math.random().toString(36).slice(2, 9)}`;

}



/**

 * @param {{ type: 'image'|'video'|'file'|'ppt', displayName: string, roomId: string, status: 'success'|'fail', detail?: string }} payload

 */

export function addSendRecord(payload) {

	const type = payload.type || 'file';

	const displayName = (payload.displayName || '').trim() || '未命名';

	const roomId = (payload.roomId || '').toUpperCase();

	const status = payload.status === 'fail' ? 'fail' : 'success';

	const detail = payload.detail != null ? String(payload.detail) : '';

	const time = Date.now();

	const record = {

		id: genSendRecordId(),

		type,

		displayName,

		roomId,

		status,

		detail: detail.slice(0, 200),

		time

	};

	let list = [];

	try {

		const raw = uni.getStorageSync(STORAGE_SEND_HISTORY);

		if (raw != null && raw !== '') {

			const parsed = typeof raw === 'string' ? JSON.parse(raw) : raw;

			if (Array.isArray(parsed)) list = parsed;

		}

	} catch (e) {

		list = [];

	}

	list.unshift(record);

	if (list.length > MAX_SEND_RECORDS) list = list.slice(0, MAX_SEND_RECORDS);

	try {

		uni.setStorageSync(STORAGE_SEND_HISTORY, JSON.stringify(list));

		updateSendRecordsTabBarBadge();

	} catch (e) {

		// ignore

	}

}



export function getSendRecords() {

	try {

		const raw = uni.getStorageSync(STORAGE_SEND_HISTORY);

		if (raw == null || raw === '') return [];

		const parsed = typeof raw === 'string' ? JSON.parse(raw) : raw;

		return Array.isArray(parsed) ? parsed : [];

	} catch (e) {

		return [];

	}

}

function getSendLastSeenLength() {

	try {

		const v = uni.getStorageSync(STORAGE_SEND_LAST_SEEN_LEN);

		const n = Number(v);

		return Number.isFinite(n) && n >= 0 ? Math.floor(n) : 0;

	} catch (e) {

		return 0;

	}

}

export function updateSendRecordsTabBarBadge() {

	try {

		const len = getSendRecords().length;

		const lastSeen = getSendLastSeenLength();

		if (len > lastSeen) {

			const text = len > 99 ? '99+' : String(len);

			uni.setTabBarBadge({

				index: TAB_BAR_SEND_RECORDS_INDEX,

				text

			});

		} else {

			uni.removeTabBarBadge({ index: TAB_BAR_SEND_RECORDS_INDEX });

		}

	} catch (e) {

		// 非 tab 页等场景忽略

	}

}

export function markSendRecordsTabSeen() {

	try {

		uni.setStorageSync(STORAGE_SEND_LAST_SEEN_LEN, getSendRecords().length);

	} catch (e) {

		// ignore

	}

	updateSendRecordsTabBarBadge();

}

export function clearSendRecords() {

	try {

		uni.removeStorageSync(STORAGE_SEND_HISTORY);

	} catch (e) {

		// ignore

	}

	try {

		uni.setStorageSync(STORAGE_SEND_LAST_SEEN_LEN, 0);

	} catch (e) {

		// ignore

	}

	updateSendRecordsTabBarBadge();

}



/** 清除发送记录与本地用户资料，保留房间号、排序、连接会话键等 */

export function clearOptionalCache() {

	clearSendRecords();

	try {

		uni.removeStorageSync(STORAGE_USER_PROFILE);

	} catch (e) {

		// ignore

	}

}



function defaultDisplayName(type) {

	const t = Date.now();

	if (type === 'image') return `图片_${t}`;

	if (type === 'video') return `视频_${t}`;

	if (type === 'ppt') return `PPT_${t}`;

	return `文件_${t}`;

}



/**

 * @returns {{ ok: true, roomId: string } | { ok: false, message: string }}

 */

export function getUploadContext() {

	try {

		const connected = uni.getStorageSync(STORAGE_PPT_WS_CONNECTED);

		const roomId = uni.getStorageSync(STORAGE_PPT_ACTIVE_ROOM);

		const on =

			connected === true ||

			connected === 'true' ||

			connected === 1 ||

			connected === '1';

		if (!on) {

			return { ok: false, message: '请先在首页连接房间' };

		}

		if (!roomId || typeof roomId !== 'string' || !ROOM_RE.test(roomId)) {

			return { ok: false, message: '当前无有效房间，请先在首页连接' };

		}

		return { ok: true, roomId: roomId.toUpperCase() };

	} catch (e) {

		return { ok: false, message: '无法读取连接状态' };

	}

}



/**

 * multipart：字段 file，附加 formData.roomId（与 URL 路径一致）

 * @param {string} filePath 本地临时路径

 * @param {{ type?: 'image'|'video'|'file'|'ppt', displayName?: string }} [meta] 发送记录用

 */

export function uploadRoomFile(filePath, meta) {

	const m = meta || {};

	const recType =

		m.type === 'image' || m.type === 'video' || m.type === 'ppt' ? m.type : 'file';

	const recName = (m.displayName && String(m.displayName).trim()) || defaultDisplayName(recType);



	const ctx = getUploadContext();

	if (!ctx.ok) {

		uni.showToast({ title: ctx.message, icon: 'none' });

		return Promise.reject(new Error(ctx.message));

	}

	const { roomId } = ctx;

	const url = buildFileUploadUrl();



	const pushRecord = (status, detail) => {

		addSendRecord({

			type: recType,

			displayName: recName,

			roomId,

			status,

			detail

		});

	};



	return new Promise((resolve, reject) => {

		uni.showLoading({ title: '准备上传…', mask: true });

		const task = uni.uploadFile({

			url,

			filePath,

			name: 'file',

			formData: { roomId },

			success: (res) => {

				uni.hideLoading();

				if (res.statusCode >= 200 && res.statusCode < 300) {

					pushRecord('success', '');

					uni.showToast({ title: '上传成功', icon: 'success' });

					resolve(res);

				} else {

					pushRecord('fail', `HTTP ${res.statusCode}`);

					uni.showToast({ title: `上传失败 (${res.statusCode})`, icon: 'none' });

					reject(new Error(String(res.statusCode)));

				}

			},

			fail: (err) => {

				uni.hideLoading();

				const raw = (err && err.errMsg) || '上传失败';

				pushRecord('fail', raw);

				uni.showToast({

					title: raw.length > 22 ? `${raw.slice(0, 22)}…` : raw,

					icon: 'none'

				});

				reject(err || new Error('upload fail'));

			}

		});

		if (task && typeof task.onProgressUpdate === 'function') {

			task.onProgressUpdate((prog) => {

				const pct = prog && typeof prog.progress === 'number' ? prog.progress : 0;

				uni.showLoading({ title: `上传中 ${pct}%`, mask: true });

			});

		}

	});

}

