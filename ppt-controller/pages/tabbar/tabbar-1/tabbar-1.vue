<template>
	<view class="page">
		<view class="custom-nav" :style="{ paddingTop: statusBarPx + 'px' }">
			<view class="custom-nav-inner" :style="{ height: navBarPx + 'px' }">
				<view class="nav-side">
					<button class="nav-icon-btn" hover-class="nav-icon-btn--hover" @click="openSettingsDialog">
						<text class="nav-icon-gear">⚙</text>
					</button>
				</view>
				<text class="nav-title">PPT 遥控</text>
				<view class="nav-side nav-side--right" />
			</view>
		</view>
		<view
			v-if="pptNotesBarVisible"
			class="ppt-notes-layer"
			:class="{ 'ppt-notes-layer--fullscreen': pptNotesFullscreen }"
			:style="pptNotesLayerStyle"
		>
			<view
				class="ppt-notes-card"
				:class="{
					'ppt-notes-card--dragging': pptNotesDragging,
					'ppt-notes-card--fullscreen': pptNotesFullscreen
				}"
				:style="pptNotesCardTransformStyle"
			>
				<view class="ppt-notes-title-row">
					<view
						class="ppt-notes-header"
						@touchstart.stop.prevent="onPptNotesDragStart"
						@touchmove.stop.prevent="onPptNotesDragMove"
						@touchend.stop="onPptNotesDragEnd"
						@touchcancel.stop="onPptNotesDragEnd"
					>
						<view class="ppt-notes-grip">
							<view v-for="gi in pptNotesGripDots" :key="gi" class="ppt-notes-grip-dot" />
						</view>
						<view class="ppt-notes-head-texts">
							<text class="ppt-notes-title">演讲者模式</text>
							<text class="ppt-notes-drag-hint">{{
								pptNotesFullscreen ? '全屏 · 下方触控板与常用功能' : '拖动此栏移动窗口'
							}}</text>
						</view>
					</view>
					<view class="ppt-notes-fs-btn" hover-class="ppt-notes-fs-btn--hover" @tap.stop="onTogglePptNotesFullscreen">
						<text class="ppt-notes-fs-icon">{{ pptNotesFullscreen ? '⊡' : '⛶' }}</text>
					</view>
					<view
						class="ppt-notes-close"
						hover-class="ppt-notes-close--hover"
						@tap.stop="onClosePptNotesBar"
					>
						<text class="ppt-notes-close-x">×</text>
					</view>
				</view>
				<scroll-view
					scroll-y
					class="ppt-notes-scroll"
					:class="{ 'ppt-notes-scroll--fullscreen': pptNotesFullscreen }"
					:show-scrollbar="false"
					:enable-flex="pptNotesFullscreen"
				>
					<view class="ppt-notes-scroll-inner">
						<text class="ppt-notes-text" selectable>{{ pptNotesDisplayText }}</text>
					</view>
				</scroll-view>
				<view v-if="pptNotesFullscreen" class="ppt-notes-pad-wrap">
					<view
						id="laser-pad-notes"
						class="laser-pad ppt-notes-laser-pad"
						@touchstart.stop.prevent="onLaserStart"
						@touchmove.stop.prevent="onLaserMove"
						@touchend.stop="onLaserEnd"
						@touchcancel.stop="onLaserCancel"
					>
						<text class="laser-hint ppt-notes-laser-hint">{{ laserPadHintText }}</text>
					</view>
				</view>
				<view v-if="pptNotesFullscreen" class="ppt-notes-quick-bar">
					<view class="ppt-notes-quick-grid">
						<view
							v-for="(t, idx) in pptNotesQuickTools"
							:key="t.cmd + '-' + idx"
							class="ppt-notes-quick-btn"
							:class="{
								'ppt-notes-quick-btn--accent': t.accent,
								'ppt-notes-quick-btn--offline': !pcReady,
								'ppt-notes-quick-btn--disabled': !pcReady
							}"
							:hover-class="pptNotesQuickHoverClass(t.accent)"
							hover-start-time="20"
							hover-stay-time="70"
							@click.stop="onFavoriteToolClick(t)"
						>
							<ppt-icon :name="t.icon" :size="28" class="ppt-notes-quick-icon" />
							<text class="ppt-notes-quick-label">{{ t.label }}</text>
						</view>
					</view>
				</view>
			</view>
		</view>
		<view class="page-body">
		<view class="card">
			<view class="room-header-row">
				<text class="room-label">PC号（与PC端显示一致）</text>
				<view class="remember-inline">
					<text class="remember-text">记住PC号</text>
					<switch :checked="rememberRoom" color="#f33e54" @change="onRememberChange" />
				</view>
			</view>
			<view class="room-input-shell" :class="{ 'room-input-shell--locked': roomLocked }">
				<input
					class="input-room-inner"
					type="text"
					maxlength="6"
					placeholder="6位大写字母或数字"
					:value="roomId"
					:disabled="roomLocked"
					@input="onRoomInput"
				/>
				<view class="room-input-divider" />
				<button class="btn-scan-inline" hover-class="btn-scan-inline--hover" @click="scanAndConnect">
					扫码
				</button>
			</view>
			<view class="row-between status-row">
				<text class="status" :class="'status--' + statusKey">{{ statusLabel }}</text>
				<button
					class="btn-connect"
					type="primary"
					size="mini"
					:loading="connecting"
					@click="toggleConnect"
				>
					{{ connectBtnText }}
				</button>
			</view>
			<view v-if="showRoomExpiredHint" class="room-expired-hint">
				<text class="room-expired-text">房间可能已失效，请重新扫码配对</text>
				<button class="btn-rescan" size="mini" @click="scanAndConnect">扫码重连</button>
			</view>
		</view>

		<view class="card card-tools-pad">
			<view class="main-tab-bar">
				<view
					class="main-tab"
					:class="{ 'main-tab--active': mainTab === 'tools' }"
					@click="setMainTab('tools')"
				>
					常用功能
				</view>
				<view
					class="main-tab"
					:class="{ 'main-tab--active': mainTab === 'pad' }"
					@click="setMainTab('pad')"
				>
					触控板
				</view>
			</view>

			<view v-show="mainTab === 'tools'" class="tools-panel">
				<text class="tools-hint">排序前 5 项为四角+中心快捷区（更多功能在「触控板」页下方，顺序可在「常用排序」页调整）</text>
				<view class="important-tools-grid">
					<view class="imp-slot imp-tl">
						<button
							v-if="importantTools[0]"
							class="imp-btn"
							:class="{
								'imp-btn--accent': importantTools[0].accent,
								'imp-btn--offline': !pcReady
							}"
							:hover-class="impToolHoverClass(importantTools[0].accent)"
							hover-start-time="20"
							hover-stay-time="70"
							:disabled="!pcReady"
							@click="onFavoriteToolClick(importantTools[0])"
						>
							<ppt-icon :name="importantTools[0].icon" :size="40" class="imp-icon" />
							<text class="imp-label">{{ importantTools[0].label }}</text>
						</button>
					</view>
					<view class="imp-slot imp-tr">
						<button
							v-if="importantTools[2]"
							class="imp-btn"
							:class="{
								'imp-btn--accent': importantTools[2].accent,
								'imp-btn--offline': !pcReady
							}"
							:hover-class="impToolHoverClass(importantTools[2].accent)"
							hover-start-time="20"
							hover-stay-time="70"
							:disabled="!pcReady"
							@click="onFavoriteToolClick(importantTools[2])"
						>
							<ppt-icon :name="importantTools[2].icon" :size="40" class="imp-icon" />
							<text class="imp-label">{{ importantTools[2].label }}</text>
						</button>
					</view>
					<view class="imp-slot imp-mid">
						<button
							v-if="importantTools[4]"
							class="imp-btn imp-btn--center"
							:class="{
								'imp-btn--accent': importantTools[4].accent,
								'imp-btn--offline': !pcReady
							}"
							:hover-class="impToolHoverClass(importantTools[4].accent)"
							hover-start-time="20"
							hover-stay-time="70"
							:disabled="!pcReady"
							@click="onFavoriteToolClick(importantTools[4])"
						>
							<ppt-icon :name="importantTools[4].icon" :size="48" class="imp-icon imp-icon--lg" />
							<text class="imp-label">{{ importantTools[4].label }}</text>
						</button>
					</view>
					<view class="imp-slot imp-bl">
						<button
							v-if="importantTools[1]"
							class="imp-btn"
							:class="{
								'imp-btn--accent': importantTools[1].accent,
								'imp-btn--offline': !pcReady
							}"
							:hover-class="impToolHoverClass(importantTools[1].accent)"
							hover-start-time="20"
							hover-stay-time="70"
							:disabled="!pcReady"
							@click="onFavoriteToolClick(importantTools[1])"
						>
							<ppt-icon :name="importantTools[1].icon" :size="40" class="imp-icon" />
							<text class="imp-label">{{ importantTools[1].label }}</text>
						</button>
					</view>
					<view class="imp-slot imp-br">
						<button
							v-if="importantTools[3]"
							class="imp-btn"
							:class="{
								'imp-btn--accent': importantTools[3].accent,
								'imp-btn--offline': !pcReady
							}"
							:hover-class="impToolHoverClass(importantTools[3].accent)"
							hover-start-time="20"
							hover-stay-time="70"
							:disabled="!pcReady"
							@click="onFavoriteToolClick(importantTools[3])"
						>
							<ppt-icon :name="importantTools[3].icon" :size="40" class="imp-icon" />
							<text class="imp-label">{{ importantTools[3].label }}</text>
						</button>
					</view>
				</view>
			</view>

			<view v-show="mainTab === 'pad'" class="pad-panel">
				<view
					id="laser-pad-main"
					class="laser-pad"
					@touchstart.stop.prevent="onLaserStart"
					@touchmove.stop.prevent="onLaserMove"
					@touchend.stop="onLaserEnd"
					@touchcancel.stop="onLaserCancel"
				>
					<text class="laser-hint">{{ laserPadHintText }}</text>
				</view>
				<text v-show="pcReady" class="laser-subhint">单击会在约 300ms 内稍延迟发出，以便识别双击</text>

				<view v-if="gridTools.length" class="nine-block nine-block--under-pad">
					<text class="nine-block-title">更多</text>
					<view class="nine-grid">
						<button
							v-for="t in gridTools"
							:key="t.id"
							class="nine-cell"
							:class="{ 'nine-cell--accent': t.accent, 'nine-cell--offline': !pcReady }"
							:hover-class="nineToolHoverClass(t.accent)"
							hover-start-time="20"
							hover-stay-time="70"
							:disabled="!pcReady"
							@click="onFavoriteToolClick(t)"
						>
							<ppt-icon :name="t.icon" :size="32" class="nine-icon" />
							<text class="nine-label">{{ t.label }}</text>
						</button>
					</view>
				</view>
			</view>
		</view>
		</view>

		<view v-if="showSettingsDialog" class="modal-mask" @click.self="closeSettingsDialog">
			<view class="modal-box modal-box--settings" @click.stop>
				<text class="modal-title">遥控设置</text>
				<text class="settings-hint">与电脑端行为一致；连接成功后会自动同步到本机接收端</text>
				<view class="settings-rows">
					<view class="settings-row">
						<text class="settings-label">截屏打开文件夹</text>
						<switch :checked="settingScreenshot" color="#f33e54" @change="onSettingScreenshotChange" />
					</view>
					<view class="settings-row">
						<text class="settings-label">传输文件打开文件夹</text>
						<switch :checked="settingTransferFolder" color="#f33e54" @change="onSettingTransferFolderChange" />
					</view>
					<view class="settings-row">
						<text class="settings-label">传输 PPT 是否打开</text>
						<switch :checked="settingTransferPpt" color="#f33e54" @change="onSettingTransferPptChange" />
					</view>
					<view class="settings-row settings-row--col">
						<view class="settings-row">
							<text class="settings-label">演讲者模式</text>
							<switch :checked="settingPptNotes" color="#f33e54" @change="onSettingPptNotesChange" />
						</view>
						<text class="settings-sub-hint">前提：PC 端已安装 pywin32（pip install pywin32）并在 PowerPoint / WPS 中按 F5 进入放映状态。</text>
					</view>
				</view>
				<button class="settings-done-btn" type="default" @click="closeSettingsDialog">完成</button>
			</view>
		</view>

		<view v-if="showTextDialog" class="modal-mask" @click.self="closeSendTextDialog">
			<view class="modal-box" @click.stop>
				<text class="modal-title">发送文本</text>
				<textarea
					class="modal-input"
					:value="sendTextInput"
					placeholder="输入要发送到电脑的内容"
					:maxlength="2000"
					auto-height
					@input="onSendTextInput"
				/>
				<view class="modal-btns">
					<button class="modal-btn modal-btn-cancel" @click="closeSendTextDialog">关闭</button>
					<button class="modal-btn modal-btn-send" type="primary" @click="submitSendText">发送</button>
				</view>
			</view>
		</view>

		<view v-if="showSpotlightDialog" class="modal-mask" @click.self="closeSpotlightDialog">
			<view class="modal-box modal-box--spotlight" @click.stop>
				<view class="spotlight-header">
					<text class="spotlight-header-title">聚光灯 / 遮罩</text>
					<view class="spotlight-close" hover-class="spotlight-close--pressed" @click.stop="closeSpotlightDialog">
						<view class="spotlight-close-x">
							<view class="spotlight-close-line"></view>
							<view class="spotlight-close-line spotlight-close-line--r"></view>
						</view>
					</view>
				</view>
				<text class="settings-hint">在投影区留出透光窗口，其余为暗遮罩。拖动下方区域移动焦点（须已连接且 PC 就绪）。</text>
				<view class="settings-row spotlight-switch-row">
					<text class="settings-label">显示遮罩</text>
					<switch :checked="spotlightOn" color="#f33e54" @change="onSpotlightSwitchChange" />
				</view>
				<text class="spotlight-size-label">透光区大小 {{ spotlightHalfPercent }}%</text>
				<slider
					class="spotlight-slider"
					:value="spotlightHalfPercent"
					min="8"
					max="38"
					step="1"
					activeColor="#f33e54"
					block-size="20"
					@change="onSpotlightSizeSliderChange"
				/>
				<view class="spotlight-pad-wrap">
					<view
						class="spotlight-pad"
						@touchstart.stop.prevent="onSpotlightPadStart"
						@touchmove.stop.prevent="onSpotlightPadMove"
						@touchend.stop="onSpotlightPadEnd"
						@touchcancel.stop="onSpotlightPadEnd"
					>
						<text class="spotlight-pad-hint">拖动移动透光区位置</text>
					</view>
				</view>
			</view>
		</view>
	</view>
</template>

<script>
import { buildWsUrl } from '../../../config/ws.js';
import {
	clearPptSession,
	getResolvedToolList,
	loadPptClientSettings,
	savePptClientSettings,
	syncPptSessionOnConnected
} from '../../../common/pptSession.js';
import { createPptSocket, WS_STATUS } from '../../../utils/pptSocket.js';
import { ROOM_RE, parseRoomFromScan } from '../../../common/roomCode.js';
import PptIcon from '../../../components/ppt-icon/ppt-icon.vue';

const STORAGE_ROOM = 'ppt_room_id';
const STORAGE_REMEMBER = 'ppt_remember_room';
const LASER_INTERVAL_MS = 70;
/** 累计位移模长达到该值（像素量级）才发 LASER，减少抖动与小位移请求 */
const LASER_SEND_MIN_MAG = 6;
const SCAN_RECONNECT_DELAY_MS = 150;
const TAP_MOVE_THRESHOLD_PX = 12;
const TAP_MAX_DURATION_MS = 320;
const DOUBLE_CLICK_MS = 300;
const DOUBLE_TAP_MAX_DISTANCE_PX = 36;
/** 首次收到 PC 端 ONLINE 时，若距发起连接已超过该毫秒数，视为手机先上线，向 PC 推送本地行为开关 */
const SETTINGS_FIRST_ONLINE_MS = 800;
const SPOTLIGHT_SEND_MIN_MS = 72;
const STORAGE_PPT_NOTES_POS = 'ppt_notes_panel_pos';

export default {
	components: { PptIcon },
	data() {
		return {
			roomId: '',
			rememberRoom: true,
			statusKey: 'idle',
			statusDetail: '',
			ppt: null,
			laserRect: null,
			lastLaserSend: 0,
			lastLaserClientX: 0,
			lastLaserClientY: 0,
			accDx: 0,
			accDy: 0,
			padTouchOriginX: 0,
			padTouchOriginY: 0,
			padTouchStartTime: 0,
			padMaxMove: 0,
			padCurrentX: 0,
			padCurrentY: 0,
			padClickTimer: null,
			padFirstTapX: 0,
			padFirstTapY: 0,
			padTouchActive: false,
			pendingConnectTimer: null,
			orderedFavoriteTools: [],
			showTextDialog: false,
			sendTextInput: '',
			mainTab: 'tools',
			statusBarPx: 20,
			navBarPx: 44,
			showSettingsDialog: false,
			settingScreenshot: true,
			settingTransferFolder: true,
			settingTransferPpt: true,
			settingPptNotes: false,
			pptNotesText: '',
			/** 服务端 ONLINE/OFFLINE 反映的 PC 端就绪状态 */
			peerPcOnline: false,
			/** 正在应用 PC 下发的 CLIENT_SETTINGS，避免回推到 PC */
			applyingFromRemote: false,
			/** 本轮 WS 会话是否已做过「首连行为开关」与对端上线的对齐 */
			settingsInitialSyncResolved: false,
			/** CONNECTING 开始时的时间戳，用于首连判断谁先在线 */
			wsConnectedAt: 0,
			showSpotlightDialog: false,
			spotlightOn: false,
			spotlightCx: 0.5,
			spotlightCy: 0.5,
			spotlightHalfPercent: 8,
			spotlightPadRect: null,
			spotlightPadActive: false,
			lastSpotlightSendAt: 0,
			pptNotesOffsetX: 0,
			pptNotesOffsetY: 0,
			pptNotesDragging: false,
			pptNotesDragStartX: 0,
			pptNotesDragStartY: 0,
			pptNotesDragOriginX: 0,
			pptNotesDragOriginY: 0,
			pptNotesWinW: 375,
			pptNotesWinH: 667,
			pptNotesFullscreen: false,
			pptNotesPreFullscreenOffsetX: 0,
			pptNotesPreFullscreenOffsetY: 0,
			/** 全屏备注层底部留白（px），避免被原生 tabBar + 底部安全区遮挡 */
			pptNotesTabBarPadPx: 56
		};
	},
	computed: {
		importantTools() {
			return this.orderedFavoriteTools.slice(0, 5);
		},
		pptNotesQuickTools() {
			return this.orderedFavoriteTools.slice(0, 8);
		},
		gridTools() {
			return this.orderedFavoriteTools.slice(5);
		},
		connecting() {
			return this.statusKey === 'connecting';
		},
		connected() {
			return this.statusKey === 'connected';
		},
		/** 已连接且 PC 接收端在同一房间就绪，才允许遥控与触控板 */
		pcReady() {
			return this.connected && this.peerPcOnline;
		},
		notesBarTopPx() {
			return this.statusBarPx + this.navBarPx;
		},
		pptNotesBarVisible() {
			return this.settingPptNotes && this.connected;
		},
		pptNotesDisplayText() {
			const t = (this.pptNotesText || '').trim();
			return t ? t : '暂无备注（或未放映）';
		},
		pptNotesLayerStyle() {
			const top = this.notesBarTopPx;
			const pad = Math.max(0, this.pptNotesTabBarPadPx || 0);
			// 非全屏：顶底占位后在层内 flex 垂直居中；全屏：铺满剩余区域
			return {
				top: top + 'px',
				bottom: pad + 'px',
				height: 'auto'
			};
		},
		pptNotesCardTransformStyle() {
			if (this.pptNotesFullscreen) {
				return {
					width: '100%',
					height: '100%',
					minHeight: '0',
					transform: 'none',
					transition: 'none'
				};
			}
			const drag = this.pptNotesDragging;
			return {
				transform: `translate3d(${this.pptNotesOffsetX}px, ${this.pptNotesOffsetY}px, 0)`,
				transition: drag ? 'none' : 'transform 0.22s ease-out'
			};
		},
		pptNotesGripDots() {
			return [1, 2, 3, 4, 5, 6];
		},
		laserPadHintText() {
			return this.pcReady
				? '滑动移动光标 · 轻点单击 · 快速连点两次双击'
				: '请先连接';
		},
		roomLocked() {
			return this.connecting || this.connected;
		},
		connectBtnText() {
			if (this.connected || this.connecting) return '断开';
			return '连接';
		},
		statusLabel() {
			const map = {
				idle: '未连接',
				connecting: '连接中…',
				connected: '已连接',
				error: this.statusDetail ? `失败：${this.statusDetail}` : '连接失败'
			};
			const base = map[this.statusKey] || map.idle;
			if (this.statusKey === 'error') return base;
			const suffix = this.peerPcOnline ? '（PC端已就绪）' : '（PC端未连接）';
			return base + suffix;
		},
		showRoomExpiredHint() {
			if (this.statusKey !== 'error') return false;
			const d = (this.statusDetail || '').toLowerCase();
			return d.includes('1006') || d.includes('1001') || d.includes('404') || d.includes('close') || d.includes('fail');
		}
	},
	onLoad() {
		try {
			const si = uni.getSystemInfoSync();
			if (typeof si.statusBarHeight === 'number' && si.statusBarHeight > 0) {
				this.statusBarPx = si.statusBarHeight;
			}
		} catch (e) {
			// ignore
		}

		this.applySettingsFromStorage();

		try {
			const remember = uni.getStorageSync(STORAGE_REMEMBER);
			if (remember === false || remember === 'false') {
				this.rememberRoom = false;
			} else {
				this.rememberRoom = true;
				const saved = uni.getStorageSync(STORAGE_ROOM);
				if (saved && typeof saved === 'string') {
					this.roomId = saved.toUpperCase().slice(0, 6);
				}
			}
		} catch (e) {
			// ignore
		}

		this.ppt = createPptSocket();
		try {
			getApp().globalData.pptSocket = this.ppt;
		} catch (e) {
			// ignore
		}
		this.ppt.setOnPeerPresence(({ online }) => {
			const wasOnline = this.peerPcOnline;
			this.peerPcOnline = !!online;
			this.syncGlobalPeerPc();
			if (
				online &&
				!wasOnline &&
				this.connected &&
				!this.settingsInitialSyncResolved
			) {
				const delta = Date.now() - this.wsConnectedAt;
				this.settingsInitialSyncResolved = true;
				if (delta >= SETTINGS_FIRST_ONLINE_MS) {
					this.pushClientSettingsToPc();
				}
			}
		});
		this.ppt.setOnClientSettingsReceived((payload) => {
			const patch = {};
			if (typeof payload.screenshot_open_folder === 'boolean') {
				patch.screenshot_open_folder = payload.screenshot_open_folder;
			}
			if (typeof payload.transfer_open_folder === 'boolean') {
				patch.transfer_open_folder = payload.transfer_open_folder;
			}
			if (typeof payload.transfer_open_ppt === 'boolean') {
				patch.transfer_open_ppt = payload.transfer_open_ppt;
			}
			if (typeof payload.ppt_notes_enabled === 'boolean') {
				patch.ppt_notes_enabled = payload.ppt_notes_enabled;
			}
			if (Object.keys(patch).length > 0) {
				this.applyingFromRemote = true;
				try {
					savePptClientSettings(patch);
					this.applySettingsFromStorage();
				} finally {
					this.applyingFromRemote = false;
				}
			}
			if (typeof payload.ppt_notes_text === 'string') {
				if (this.settingPptNotes || payload.ppt_notes_enabled === true) {
					this.pptNotesText = payload.ppt_notes_text;
				}
			}
		});
		this.ppt.setOnVersionMismatch(({ pcVersion, minRequired }) => {
				uni.showModal({
					title: '小程序版本过低',
					content: `当前 PC 端要求小程序版本 ≥ ${minRequired}，请在微信中更新小程序后重试。`,
					showCancel: false,
					confirmText: '知道了'
				});
			});
			this.ppt.setOnScreenshotDone(({ filename }) => {
				const name = filename ? `已保存：${filename}` : '截图已保存到PC';
				uni.showToast({ title: name, icon: 'success', duration: 2500 });
			});
			this.ppt.setOnPptNotesReceived(({ text }) => {
			if (!this.settingPptNotes) return;
			this.pptNotesText = typeof text === 'string' ? text : '';
		});
		this.ppt.setOnStatusChange((status, errMsg) => {
			if (status === WS_STATUS.DISCONNECTED) {
				this.statusKey = 'idle';
				this.statusDetail = '';
				this.peerPcOnline = false;
				this.syncGlobalPeerPc();
				this.settingsInitialSyncResolved = false;
				this.wsConnectedAt = 0;
				this.pptNotesText = '';
				this.clearPadClickTimer();
				clearPptSession();
			} else if (status === WS_STATUS.CONNECTING) {
				this.statusKey = 'connecting';
				this.statusDetail = '';
				this.wsConnectedAt = Date.now();
				this.settingsInitialSyncResolved = false;
			} else if (status === WS_STATUS.CONNECTED) {
				this.statusKey = 'connected';
				this.statusDetail = '';
				syncPptSessionOnConnected(this.roomId);
			} else if (status === WS_STATUS.ERROR) {
				this.statusKey = 'error';
				this.statusDetail = errMsg || '';
				this.peerPcOnline = false;
				this.syncGlobalPeerPc();
				this.settingsInitialSyncResolved = false;
				this.wsConnectedAt = 0;
				this.pptNotesText = '';
				clearPptSession();
			}
		});
		this.loadFavoriteToolsOrder();
		this._loadPptNotesPanelPos();
		try {
			const si = uni.getSystemInfoSync();
			if (typeof si.windowWidth === 'number') this.pptNotesWinW = si.windowWidth;
			if (typeof si.windowHeight === 'number') this.pptNotesWinH = si.windowHeight;
		} catch (e) {
			// ignore
		}
		this._updatePptNotesTabBarPad();
		this._clampPptNotesOffset();
	},
	onShow() {
		this.loadFavoriteToolsOrder();
		this._updatePptNotesTabBarPad();
		this._clampPptNotesOffset();
	},
	onUnload() {
		this.clearPadClickTimer();
		if (this.pendingConnectTimer != null) {
			clearTimeout(this.pendingConnectTimer);
			this.pendingConnectTimer = null;
		}
		const pptRef = this.ppt;
		if (pptRef) {
			pptRef.disconnect();
			this.ppt = null;
		}
		try {
			const app = getApp();
			if (app.globalData.pptSocket === pptRef) {
				app.globalData.pptSocket = null;
			}
			app.globalData.peerPcOnline = false;
		} catch (e) {
			// ignore
		}
	},
	methods: {
		syncGlobalPeerPc() {
			try {
				getApp().globalData.peerPcOnline = !!this.peerPcOnline;
			} catch (e) {
				// ignore
			}
		},
		/** 已连接时：按下态样式类；未连接无按压反馈 */
		impToolHoverClass(accent) {
			if (!this.pcReady) return 'tool-press-none';
			return accent ? 'imp-press imp-press--accent' : 'imp-press';
		},
		pptNotesQuickHoverClass(accent) {
			if (!this.pcReady) return 'tool-press-none';
			return accent ? 'ppt-notes-q-press ppt-notes-q-press--accent' : 'ppt-notes-q-press';
		},
		nineToolHoverClass(accent) {
			if (!this.pcReady) return 'tool-press-none';
			return accent ? 'nine-press nine-press--accent' : 'nine-press';
		},
		applySettingsFromStorage() {
			const s = loadPptClientSettings();
			this.settingScreenshot = s.screenshot_open_folder;
			this.settingTransferFolder = s.transfer_open_folder;
			this.settingTransferPpt = s.transfer_open_ppt;
			this.settingPptNotes = s.ppt_notes_enabled;
		},
		openSettingsDialog() {
			this.applySettingsFromStorage();
			this.showSettingsDialog = true;
		},
		closeSettingsDialog() {
			this.showSettingsDialog = false;
		},
		pushClientSettingsToPc() {
			if (!this.ppt || !this.connected || this.applyingFromRemote) return;
			const s = loadPptClientSettings();
			this.ppt
				.sendCmd('CLIENT_SETTINGS', {
					screenshot_open_folder: s.screenshot_open_folder,
					transfer_open_folder: s.transfer_open_folder,
					transfer_open_ppt: s.transfer_open_ppt,
					ppt_notes_enabled: s.ppt_notes_enabled
				})
				.catch(() => {});
		},
		onSettingScreenshotChange(e) {
			if (this.applyingFromRemote) return;
			const v = !!(e.detail && e.detail.value);
			savePptClientSettings({ screenshot_open_folder: v });
			this.settingScreenshot = v;
			this.pushClientSettingsToPc();
		},
		onSettingTransferFolderChange(e) {
			if (this.applyingFromRemote) return;
			const v = !!(e.detail && e.detail.value);
			savePptClientSettings({ transfer_open_folder: v });
			this.settingTransferFolder = v;
			this.pushClientSettingsToPc();
		},
		onSettingTransferPptChange(e) {
			if (this.applyingFromRemote) return;
			const v = !!(e.detail && e.detail.value);
			savePptClientSettings({ transfer_open_ppt: v });
			this.settingTransferPpt = v;
			this.pushClientSettingsToPc();
		},
		onSettingPptNotesChange(e) {
			if (this.applyingFromRemote) return;
			const v = !!(e.detail && e.detail.value);
			savePptClientSettings({ ppt_notes_enabled: v });
			this.settingPptNotes = v;
			if (!v) {
				this.pptNotesText = '';
			}
			this.pushClientSettingsToPc();
		},
		onClosePptNotesBar() {
			if (this.applyingFromRemote) return;
			this.pptNotesFullscreen = false;
			savePptClientSettings({ ppt_notes_enabled: false });
			this.settingPptNotes = false;
			this.pptNotesText = '';
			this.pushClientSettingsToPc();
		},
		onTogglePptNotesFullscreen() {
			if (this.pptNotesFullscreen) {
				this.pptNotesFullscreen = false;
				this.pptNotesOffsetX = this.pptNotesPreFullscreenOffsetX;
				this.pptNotesOffsetY = this.pptNotesPreFullscreenOffsetY;
			} else {
				this.pptNotesPreFullscreenOffsetX = this.pptNotesOffsetX;
				this.pptNotesPreFullscreenOffsetY = this.pptNotesOffsetY;
				this.pptNotesDragging = false;
				this.pptNotesFullscreen = true;
			}
			this.feedback();
		},
		_loadPptNotesPanelPos() {
			try {
				const pos = uni.getStorageSync(STORAGE_PPT_NOTES_POS);
				if (pos && typeof pos === 'object') {
					if (typeof pos.x === 'number') this.pptNotesOffsetX = pos.x;
					if (typeof pos.y === 'number') this.pptNotesOffsetY = pos.y;
				}
			} catch (e) {
				// ignore
			}
		},
		_updatePptNotesTabBarPad() {
			try {
				const si = uni.getSystemInfoSync();
				const safeBottom = (si.safeAreaInsets && si.safeAreaInsets.bottom) || 0;
				// #ifdef MP-WEIXIN
				// iOS：页面可用高度通常已不含原生 tabBar，再减固定 tabBar 高度会在操作栏与导航栏之间留出大块空白。
				// Android：底部区域常与 tabBar 重叠，需预留 tabBar 高度 + 安全区。
				// iOS：全屏层 bottom 用 0 贴齐页面可视区底（已在 tabBar 之上），勿再用 safeAreaInsets.bottom 整体上推，否则会与 tabBar 间残留空白；底部触控区用 CSS env(safe-area-inset-bottom) 留白即可。
				if (si.platform === 'ios') {
					this.pptNotesTabBarPadPx = 0;
				} else {
					this.pptNotesTabBarPadPx = 56 + safeBottom;
				}
				// #endif
				// #ifndef MP-WEIXIN
				this.pptNotesTabBarPadPx = Math.max(8, safeBottom);
				// #endif
			} catch (e) {
				this.pptNotesTabBarPadPx = 56;
			}
		},
		_clampPptNotesOffset() {
			const w = this.pptNotesWinW || 375;
			const h = this.pptNotesWinH || 667;
			const maxX = Math.max(40, Math.floor(w * 0.2));
			const baseTop = this.statusBarPx + this.navBarPx;
			const tabPad = Math.max(0, this.pptNotesTabBarPadPx || 0);
			const bottomReserve = tabPad + 32;
			const usableH = Math.max(160, h - baseTop - bottomReserve);
			const maxDy = Math.max(56, Math.floor(usableH * 0.45));
			this.pptNotesOffsetX = Math.max(-maxX, Math.min(maxX, this.pptNotesOffsetX));
			this.pptNotesOffsetY = Math.max(-maxDy, Math.min(maxDy, this.pptNotesOffsetY));
		},
		_pptNotesTouchXY(e) {
			const t = (e.touches && e.touches[0]) || (e.changedTouches && e.changedTouches[0]);
			if (!t) return null;
			const x = t.clientX != null ? t.clientX : t.pageX;
			const y = t.clientY != null ? t.clientY : t.pageY;
			if (typeof x !== 'number' || typeof y !== 'number' || Number.isNaN(x) || Number.isNaN(y)) return null;
			return { x, y };
		},
		onPptNotesDragStart(e) {
			if (this.pptNotesFullscreen) return;
			const p = this._pptNotesTouchXY(e);
			if (!p) return;
			this.pptNotesDragStartX = p.x;
			this.pptNotesDragStartY = p.y;
			this.pptNotesDragOriginX = this.pptNotesOffsetX;
			this.pptNotesDragOriginY = this.pptNotesOffsetY;
			this.pptNotesDragging = true;
		},
		onPptNotesDragMove(e) {
			if (this.pptNotesFullscreen || !this.pptNotesDragging) return;
			const p = this._pptNotesTouchXY(e);
			if (!p) return;
			const dx = p.x - this.pptNotesDragStartX;
			const dy = p.y - this.pptNotesDragStartY;
			this.pptNotesOffsetX = this.pptNotesDragOriginX + dx;
			this.pptNotesOffsetY = this.pptNotesDragOriginY + dy;
			this._clampPptNotesOffset();
		},
		onPptNotesDragEnd() {
			if (this.pptNotesFullscreen || !this.pptNotesDragging) return;
			this.pptNotesDragging = false;
			this._clampPptNotesOffset();
			try {
				uni.setStorageSync(STORAGE_PPT_NOTES_POS, {
					x: this.pptNotesOffsetX,
					y: this.pptNotesOffsetY
				});
			} catch (err) {
				// ignore
			}
		},
		setMainTab(tab) {
			this.mainTab = tab;
		},
		loadFavoriteToolsOrder() {
			this.orderedFavoriteTools = getResolvedToolList();
		},
		onRoomInput(e) {
			const v = (e.detail.value || '').toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 6);
			this.roomId = v;
		},
		onRememberChange(e) {
			this.rememberRoom = !!(e.detail && e.detail.value);
			try {
				uni.setStorageSync(STORAGE_REMEMBER, this.rememberRoom);
				if (!this.rememberRoom) {
					uni.removeStorageSync(STORAGE_ROOM);
				} else if (this.roomId && ROOM_RE.test(this.roomId)) {
					uni.setStorageSync(STORAGE_ROOM, this.roomId);
				}
			} catch (err) {
				// ignore
			}
		},
		persistRoom() {
			if (!this.rememberRoom) return;
			try {
				if (this.roomId && ROOM_RE.test(this.roomId)) {
					uni.setStorageSync(STORAGE_ROOM, this.roomId);
				}
			} catch (e) {
				// ignore
			}
		},
		/** 当前 roomId 已合法时直接发起连接（扫码等路径，不再弹校验文案） */
		startConnect() {
			if (!this.ppt) return;
			const id = (this.roomId || '').trim().toUpperCase();
			if (!ROOM_RE.test(id)) return;
			this.roomId = id;
			this.persistRoom();
			this.ppt.connect(buildWsUrl(id));
		},
		ensureConnectFromInput() {
			if (!this.ppt) return;
			const id = (this.roomId || '').trim().toUpperCase();
			if (!ROOM_RE.test(id)) {
				uni.showToast({ title: '请输入6位房间号', icon: 'none' });
				return;
			}
			this.roomId = id;
			this.persistRoom();
			this.ppt.connect(buildWsUrl(id));
		},
		toggleConnect() {
			if (!this.ppt) return;
			if (this.connected || this.connecting) {
				this.ppt.disconnect();
				return;
			}
			this.ensureConnectFromInput();
		},
		scanAndConnect() {
			if (!this.ppt) return;
			if (this.pendingConnectTimer != null) {
				clearTimeout(this.pendingConnectTimer);
				this.pendingConnectTimer = null;
			}
			uni.scanCode({
				success: (res) => {
					const parsed = parseRoomFromScan(res.result);
					if (!parsed) {
						uni.showToast({ title: '请扫描电脑端配对二维码', icon: 'none' });
						return;
					}
					this.roomId = parsed;
					this.persistRoom();
					const needDisconnect = this.connected || this.connecting;
					if (needDisconnect) {
						this.ppt.disconnect();
					}
					const delay = needDisconnect ? SCAN_RECONNECT_DELAY_MS : 0;
					this.pendingConnectTimer = setTimeout(() => {
						this.pendingConnectTimer = null;
						if (!this.ppt) return;
						this.startConnect();
					}, delay);
				},
				fail: (err) => {
					const msg = (err && err.errMsg) || '';
					if (/取消|cancel/i.test(msg)) return;
					uni.showToast({
						title: msg.length > 24 ? `${msg.slice(0, 24)}…` : msg || '扫码失败',
						icon: 'none'
					});
				}
			});
		},
		feedback() {
			// #ifdef MP-WEIXIN
			uni.vibrateShort({});
			// #endif
		},
		onFavoriteToolClick(t) {
			if (!this.ppt || !this.pcReady) {
				uni.showToast({ title: '请先连接', icon: 'none' });
				return;
			}
			if (t.special === 'sendText') {
				this.sendTextInput = '';
				this.showTextDialog = true;
				return;
			}
			if (t.special === 'timer') {
				uni.navigateTo({ url: '/pages/timer/timer' });
				return;
			}
			if (t.special === 'spotlight') {
				this.showSpotlightDialog = true;
				if (this.ppt && this.pcReady) {
					this.spotlightOn = true;
					this.$nextTick(() => this.pushSpotlightShow());
				} else {
					uni.showToast({ title: '请先连接且等待PC就绪', icon: 'none' });
					this.spotlightOn = false;
				}
				return;
			}
			this.sendCmd(t.cmd);
		},
		closeSpotlightDialog() {
			if (this.spotlightOn) {
				this.pushSpotlightHide();
			}
			this.spotlightOn = false;
			this.showSpotlightDialog = false;
			this.spotlightPadActive = false;
			this.spotlightPadRect = null;
		},
		spotlightNormHalf() {
			return Math.min(0.45, Math.max(0.04, this.spotlightHalfPercent / 100));
		},
		pushSpotlightShow() {
			if (!this.ppt || !this.pcReady) return;
			const h = this.spotlightNormHalf();
			this.ppt
				.sendCmd('SPOTLIGHT_SHOW', {
					cx: this.spotlightCx,
					cy: this.spotlightCy,
					halfW: h,
					halfH: h
				})
				.catch(() => {});
		},
		pushSpotlightUpdate() {
			if (!this.ppt || !this.pcReady || !this.spotlightOn) return;
			const now = Date.now();
			if (now - this.lastSpotlightSendAt < SPOTLIGHT_SEND_MIN_MS) return;
			this.lastSpotlightSendAt = now;
			const hh = this.spotlightNormHalf();
			this.ppt
				.sendCmd('SPOTLIGHT_UPDATE', {
					cx: this.spotlightCx,
					cy: this.spotlightCy,
					halfW: hh,
					halfH: hh
				})
				.catch(() => {});
		},
		pushSpotlightHide() {
			if (!this.ppt || !this.connected) return;
			this.ppt.sendCmd('SPOTLIGHT_HIDE').catch(() => {});
		},
		onSpotlightSwitchChange(e) {
			const v = !!(e.detail && e.detail.value);
			this.spotlightOn = v;
			if (!this.ppt || !this.pcReady) {
				if (v) {
					uni.showToast({ title: '请先连接且等待PC就绪', icon: 'none' });
					this.spotlightOn = false;
				}
				return;
			}
			if (v) this.pushSpotlightShow();
			else this.pushSpotlightHide();
		},
		onSpotlightSizeSliderChange(e) {
			const raw = e.detail && e.detail.value;
			const n = typeof raw === 'number' ? raw : parseInt(raw, 10);
			if (!Number.isFinite(n)) return;
			this.spotlightHalfPercent = Math.min(38, Math.max(8, n));
			if (this.spotlightOn && this.ppt && this.pcReady) {
				this.lastSpotlightSendAt = 0;
				this.pushSpotlightUpdate();
			}
		},
		onSpotlightPadStart(e) {
			if (!this.pcReady || !this.spotlightOn) {
				this.spotlightPadRect = null;
				this.spotlightPadActive = false;
				return;
			}
			this.spotlightPadActive = true;
			uni.createSelectorQuery()
				.in(this)
				.select('.spotlight-pad')
				.boundingClientRect((rect) => {
					if (!rect || !this.spotlightPadActive) return;
					this.spotlightPadRect = rect;
					const t = e.touches && e.touches[0];
					if (!t) return;
					this._applySpotlightFromPadTouch(t.clientX, t.clientY);
				})
				.exec();
		},
		onSpotlightPadMove(e) {
			if (!this.spotlightPadRect || !this.spotlightPadActive || !this.pcReady || !this.spotlightOn) return;
			const t = e.touches && e.touches[0];
			if (!t) return;
			this._applySpotlightFromPadTouch(t.clientX, t.clientY);
		},
		onSpotlightPadEnd() {
			this.spotlightPadActive = false;
			this.spotlightPadRect = null;
			if (this.spotlightOn && this.ppt && this.pcReady) {
				this.lastSpotlightSendAt = 0;
				this.pushSpotlightUpdate();
			}
		},
		_applySpotlightFromPadTouch(clientX, clientY) {
			const r = this.spotlightPadRect;
			if (!r || r.width <= 0 || r.height <= 0) return;
			let cx = (clientX - r.left) / r.width;
			let cy = (clientY - r.top) / r.height;
			const hh = this.spotlightNormHalf();
			cx = Math.min(1 - hh, Math.max(hh, cx));
			cy = Math.min(1 - hh, Math.max(hh, cy));
			this.spotlightCx = cx;
			this.spotlightCy = cy;
			this.pushSpotlightUpdate();
		},
		closeSendTextDialog() {
			this.showTextDialog = false;
			this.sendTextInput = '';
		},
		onSendTextInput(e) {
			this.sendTextInput = (e.detail && e.detail.value) || '';
		},
		submitSendText() {
			const text = (this.sendTextInput || '').trim();
			if (!text) {
				uni.showToast({ title: '请输入内容', icon: 'none' });
				return;
			}
			if (!this.ppt || !this.pcReady) {
				uni.showToast({ title: '请先连接', icon: 'none' });
				return;
			}
			this.ppt
				.sendCmd('SEND_TEXT', { text })
				.then(() => {
					this.feedback();
					this.closeSendTextDialog();
					uni.showToast({ title: '已发送', icon: 'success' });
				})
				.catch((err) => {
					const msg = (err && err.errMsg) || '发送失败';
					uni.showToast({ title: msg, icon: 'none' });
				});
		},
		sendCmd(cmd) {
			if (!this.ppt || !this.pcReady) {
				uni.showToast({ title: '请先连接', icon: 'none' });
				return;
			}
			this.ppt
				.sendCmd(cmd)
				.then(() => this.feedback())
				.catch((err) => {
					const msg = (err && err.errMsg) || '发送失败';
					uni.showToast({ title: msg, icon: 'none' });
				});
		},
		clearPadClickTimer() {
			if (this.padClickTimer != null) {
				clearTimeout(this.padClickTimer);
				this.padClickTimer = null;
			}
		},
		scheduleSingleClickFromTap(tapX, tapY) {
			this.clearPadClickTimer();
			this.padFirstTapX = tapX;
			this.padFirstTapY = tapY;
			this.padClickTimer = setTimeout(() => {
				this.padClickTimer = null;
				if (!this.ppt || !this.pcReady) return;
				this.ppt.sendCmd('MOUSE_CLICK', { button: 'left', count: 1 }).catch(() => {});
			}, DOUBLE_CLICK_MS);
		},
		flushPendingLaserMove(options) {
			const bypassMin = options && options.bypassMin;
			if (!this.ppt || !this.pcReady) {
				this.accDx = 0;
				this.accDy = 0;
				return;
			}
			if (this.accDx === 0 && this.accDy === 0) return;
			const dx = this.accDx;
			const dy = this.accDy;
			if (!bypassMin && Math.hypot(dx, dy) < LASER_SEND_MIN_MAG) {
				this.accDx = 0;
				this.accDy = 0;
				return;
			}
			this.accDx = 0;
			this.accDy = 0;
			this.ppt.sendCmd('LASER', { dx, dy }).catch(() => {});
		},
		_laserPadQueryFromEvent(e) {
			const id = e && e.currentTarget && e.currentTarget.id;
			if (id === 'laser-pad-notes') return '#laser-pad-notes';
			return '#laser-pad-main';
		},
		onLaserStart(e) {
			if (!this.pcReady) return;
			const t = e.touches && e.touches[0];
			if (!t) return;
			this.padTouchActive = true;
			this.padTouchOriginX = t.clientX;
			this.padTouchOriginY = t.clientY;
			this.padTouchStartTime = Date.now();
			this.padMaxMove = 0;
			this.padCurrentX = t.clientX;
			this.padCurrentY = t.clientY;
			const sel = this._laserPadQueryFromEvent(e);
			uni.createSelectorQuery()
				.in(this)
				.select(sel)
				.boundingClientRect((rect) => {
					if (!rect || !this.pcReady || !this.padTouchActive) return;
					this.laserRect = rect;
					this.lastLaserClientX = this.padCurrentX;
					this.lastLaserClientY = this.padCurrentY;
					this.accDx = 0;
					this.accDy = 0;
				})
				.exec();
		},
		onLaserMove(e) {
			if (!this.laserRect || !this.pcReady) return;
			const t = e.touches && e.touches[0];
			if (!t) return;
			this.padCurrentX = t.clientX;
			this.padCurrentY = t.clientY;
			const move = Math.hypot(t.clientX - this.padTouchOriginX, t.clientY - this.padTouchOriginY);
			if (move > this.padMaxMove) this.padMaxMove = move;
			this.flushLaser(e, false);
		},
		onLaserCancel() {
			this.padTouchActive = false;
			this.clearPadClickTimer();
			this.laserRect = null;
			this.accDx = 0;
			this.accDy = 0;
		},
		onLaserEnd(e) {
			this.padTouchActive = false;
			const t = e.changedTouches && e.changedTouches[0];
			if (t) {
				const move = Math.hypot(t.clientX - this.padTouchOriginX, t.clientY - this.padTouchOriginY);
				if (move > this.padMaxMove) this.padMaxMove = move;
			}
			this.flushPendingLaserMove({ bypassMin: true });
			const duration = Date.now() - this.padTouchStartTime;
			const isTap =
				this.padMaxMove < TAP_MOVE_THRESHOLD_PX &&
				duration < TAP_MAX_DURATION_MS &&
				this.pcReady &&
				this.ppt;
			if (isTap && t) {
				const tapX = t.clientX;
				const tapY = t.clientY;
				if (this.padClickTimer != null) {
					const dx = tapX - this.padFirstTapX;
					const dy = tapY - this.padFirstTapY;
					if (Math.hypot(dx, dy) <= DOUBLE_TAP_MAX_DISTANCE_PX) {
						this.clearPadClickTimer();
						this.ppt.sendCmd('MOUSE_CLICK', { button: 'left', count: 2 }).catch(() => {});
					} else {
						this.clearPadClickTimer();
						this.ppt.sendCmd('MOUSE_CLICK', { button: 'left', count: 1 }).catch(() => {});
						this.scheduleSingleClickFromTap(tapX, tapY);
					}
				} else {
					this.scheduleSingleClickFromTap(tapX, tapY);
				}
			} else {
				this.clearPadClickTimer();
			}
			this.laserRect = null;
			this.accDx = 0;
			this.accDy = 0;
		},
		flushLaser(e, force) {
			const t = e.touches && e.touches[0];
			if (!t || !this.laserRect || !this.ppt) return;
			const dx = t.clientX - this.lastLaserClientX;
			const dy = t.clientY - this.lastLaserClientY;
			this.lastLaserClientX = t.clientX;
			this.lastLaserClientY = t.clientY;
			const sendDx = dx + this.accDx;
			const sendDy = dy + this.accDy;
			if (sendDx === 0 && sendDy === 0) return;
			const now = Date.now();
			if (!force && now - this.lastLaserSend < LASER_INTERVAL_MS) {
				this.accDx = sendDx;
				this.accDy = sendDy;
				return;
			}
			if (!force && Math.hypot(sendDx, sendDy) < LASER_SEND_MIN_MAG) {
				this.accDx = sendDx;
				this.accDy = sendDy;
				return;
			}
			this.accDx = 0;
			this.accDy = 0;
			this.lastLaserSend = now;
			this.ppt.sendCmd('LASER', { dx: sendDx, dy: sendDy }).catch(() => {});
		}
	}
};
</script>

<style scoped>
.page {
	min-height: 100vh;
	background: #f0f0f0;
	box-sizing: border-box;
}

.custom-nav {
	width: 100%;
	background: #f8f8f8;
	box-sizing: border-box;
	border-bottom: 1rpx solid #e8e8e8;
}

.custom-nav-inner {
	display: flex;
	flex-direction: row;
	align-items: center;
	justify-content: space-between;
	padding: 0 8rpx 0 16rpx;
	box-sizing: border-box;
}

.nav-side {
	width: 88rpx;
	flex-shrink: 0;
	display: flex;
	align-items: center;
	justify-content: flex-start;
}

.nav-side--right {
	justify-content: flex-end;
}

.nav-icon-btn {
	width: 72rpx;
	height: 72rpx;
	margin: 0;
	padding: 0;
	display: flex;
	align-items: center;
	justify-content: center;
	background: transparent;
	border: none;
	border-radius: 50%;
}

.nav-icon-btn::after {
	border: none;
}

.nav-icon-btn--hover {
	opacity: 0.65;
}

.nav-icon-gear {
	font-size: 40rpx;
	line-height: 1;
	color: #333;
}

.nav-title {
	flex: 1;
	text-align: center;
	font-size: 34rpx;
	font-weight: 600;
	color: #333;
}

/* 备注浮层：外层穿透点击，卡片可点、可拖 */
.ppt-notes-layer {
	position: fixed;
	left: 24rpx;
	right: 24rpx;
	z-index: 500;
	pointer-events: none;
}

/* 非全屏：在顶栏与底部预留之间水平、垂直居中 */
.ppt-notes-layer:not(.ppt-notes-layer--fullscreen) {
	display: flex;
	align-items: center;
	justify-content: center;
}

.ppt-notes-layer--fullscreen {
	left: 0;
	right: 0;
	box-sizing: border-box;
}

.ppt-notes-card {
	pointer-events: auto;
	display: flex;
	flex-direction: column;
	min-height: 0;
	border-radius: 20rpx;
	overflow: hidden;
	background: linear-gradient(165deg, rgba(38, 40, 48, 0.78) 0%, rgba(22, 23, 28, 0.82) 100%);
	border: 1rpx solid rgba(255, 255, 255, 0.12);
	box-shadow: 0 12rpx 48rpx rgba(0, 0, 0, 0.38), 0 0 0 1rpx rgba(255, 255, 255, 0.05) inset;
	backdrop-filter: blur(10px);
	-webkit-backdrop-filter: blur(10px);
}

.ppt-notes-card--fullscreen {
	border-radius: 0;
	height: 100%;
	width: 100%;
	box-sizing: border-box;
}

.ppt-notes-card--dragging {
	box-shadow: 0 20rpx 56rpx rgba(0, 0, 0, 0.55);
}

.ppt-notes-title-row {
	display: flex;
	flex-direction: row;
	align-items: stretch;
	border-bottom: 1rpx solid rgba(255, 255, 255, 0.1);
}

.ppt-notes-header {
	flex: 1;
	min-width: 0;
	display: flex;
	flex-direction: row;
	align-items: center;
	padding: 16rpx 8rpx 14rpx 16rpx;
	gap: 14rpx;
	touch-action: none;
}

.ppt-notes-grip {
	display: grid;
	grid-template-columns: repeat(3, 8rpx);
	gap: 5rpx 6rpx;
	align-content: center;
	opacity: 0.55;
}

.ppt-notes-grip-dot {
	width: 8rpx;
	height: 8rpx;
	border-radius: 50%;
	background: rgba(255, 255, 255, 0.75);
}

.ppt-notes-head-texts {
	flex: 1;
	min-width: 0;
	display: flex;
	flex-direction: column;
	gap: 4rpx;
}

.ppt-notes-title {
	font-size: 26rpx;
	font-weight: 600;
	color: rgba(255, 255, 255, 0.88);
	letter-spacing: 1rpx;
}

.ppt-notes-drag-hint {
	font-size: 20rpx;
	color: rgba(255, 255, 255, 0.42);
}

.ppt-notes-scroll {
	max-height: 300rpx;
	height: 300rpx;
	box-sizing: border-box;
	flex-shrink: 0;
}

.ppt-notes-scroll--fullscreen {
	flex: 1;
	min-height: 0;
	height: 0;
	max-height: none;
	width: 100%;
}

.ppt-notes-scroll-inner {
	padding: 16rpx 20rpx 56rpx;
	box-sizing: border-box;
}

.ppt-notes-text {
	display: block;
	font-size: 28rpx;
	line-height: 1.55;
	color: rgba(255, 255, 255, 0.92);
	word-break: break-word;
	white-space: pre-wrap;
}

.ppt-notes-close {
	flex-shrink: 0;
	width: 64rpx;
	height: 64rpx;
	margin: 8rpx 8rpx 8rpx 0;
	box-sizing: border-box;
	display: flex;
	align-items: center;
	justify-content: center;
	align-self: center;
	border-radius: 50%;
	overflow: hidden;
	background: rgba(255, 255, 255, 0.14);
}

.ppt-notes-close--hover {
	background: rgba(255, 255, 255, 0.22);
}

.ppt-notes-close-x {
	font-size: 36rpx;
	line-height: 1;
	color: rgba(255, 255, 255, 0.92);
	font-weight: 300;
}

.ppt-notes-fs-btn {
	flex-shrink: 0;
	align-self: center;
	width: 64rpx;
	height: 64rpx;
	margin: 8rpx 4rpx 8rpx 0;
	padding: 0;
	display: flex;
	align-items: center;
	justify-content: center;
	border-radius: 50%;
	background: rgba(255, 255, 255, 0.12);
	box-sizing: border-box;
}

.ppt-notes-fs-btn--hover {
	background: rgba(255, 255, 255, 0.22);
}

.ppt-notes-fs-icon {
	font-size: 34rpx;
	line-height: 1;
	color: rgba(255, 255, 255, 0.92);
	font-weight: 400;
}

.ppt-notes-pad-wrap {
	flex-shrink: 0;
	padding: 0 16rpx 8rpx;
	box-sizing: border-box;
	border-top: 1rpx solid rgba(255, 255, 255, 0.08);
}

.ppt-notes-laser-hint {
	font-size: 22rpx;
	padding: 0 16rpx;
}

.ppt-notes-quick-bar {
	flex-shrink: 0;
	padding: 10rpx 16rpx 12rpx;
	/* 全屏时仅此处接底：用安全区内边距代替整层 bottom，避免 iOS 小程序重复计入 safeArea 产生缝隙 */
	padding-bottom: calc(12rpx + constant(safe-area-inset-bottom));
	padding-bottom: calc(12rpx + env(safe-area-inset-bottom));
	box-sizing: border-box;
	border-top: 1rpx solid rgba(255, 255, 255, 0.1);
	background: rgba(0, 0, 0, 0.15);
}

.ppt-notes-quick-grid {
	display: grid;
	grid-template-columns: repeat(4, 1fr);
	gap: 8rpx 10rpx;
}

.ppt-notes-quick-btn {
	min-height: 72rpx;
	padding: 8rpx 4rpx;
	margin: 0;
	display: flex;
	flex-direction: column;
	align-items: center;
	justify-content: center;
	gap: 4rpx;
	background: rgba(255, 255, 255, 0.1);
	color: rgba(255, 255, 255, 0.95);
	border-radius: 10rpx;
	box-sizing: border-box;
	line-height: 1.2;
	-webkit-tap-highlight-color: transparent;
}

.ppt-notes-quick-btn--accent {
	background: linear-gradient(145deg, rgba(255, 90, 106, 0.85), rgba(243, 62, 84, 0.9));
	color: #fff;
}

.ppt-notes-quick-btn--disabled {
	opacity: 0.42;
}

.ppt-notes-quick-btn--offline {
	border: 1rpx solid rgba(255, 255, 255, 0.25);
}

.ppt-notes-quick-btn--offline.ppt-notes-quick-btn--disabled {
	opacity: 0.55;
}

.ppt-notes-q-press {
	opacity: 0.88;
	background: rgba(255, 255, 255, 0.22) !important;
}

.ppt-notes-quick-btn--accent.ppt-notes-q-press--accent {
	background: linear-gradient(145deg, rgba(232, 56, 77, 0.92), rgba(207, 42, 62, 0.95)) !important;
	opacity: 0.93;
}

.ppt-notes-quick-icon {
	display: flex;
	align-items: center;
	justify-content: center;
	margin-bottom: 2rpx;
	opacity: 0.88;
}

.ppt-notes-quick-label {
	font-size: 18rpx;
	line-height: 1.2;
	text-align: center;
	max-width: 100%;
	overflow: hidden;
	text-overflow: ellipsis;
	display: -webkit-box;
	-webkit-line-clamp: 2;
	line-clamp: 2;
	-webkit-box-orient: vertical;
	word-break: break-all;
}

.page-body {
	padding: 24rpx;
	padding-bottom: 48rpx;
	box-sizing: border-box;
	min-height: 0;
}

.card {
	background: #fff;
	border-radius: 16rpx;
	padding: 28rpx;
	margin-bottom: 24rpx;
	box-shadow: 0 4rpx 24rpx rgba(0, 0, 0, 0.06);
}

.row-between {
	display: flex;
	align-items: center;
	justify-content: space-between;
}

.room-header-row {
	display: flex;
	align-items: center;
	justify-content: space-between;
	gap: 16rpx;
	margin-bottom: 16rpx;
}

.room-label {
	flex: 1;
	font-size: 26rpx;
	color: #666;
	line-height: 1.4;
	min-width: 0;
}

.remember-inline {
	display: flex;
	align-items: center;
	gap: 10rpx;
	flex-shrink: 0;
}

.remember-text {
	font-size: 24rpx;
	color: #888;
	white-space: nowrap;
}

.room-input-shell {
	display: flex;
	flex-direction: row;
	align-items: center;
	background: #f5f5f5;
	border-radius: 12rpx;
	border: 2rpx solid #ebebeb;
	overflow: hidden;
	min-height: 88rpx;
	margin-bottom: 0;
	box-sizing: border-box;
}

.room-input-shell--locked {
	opacity: 0.92;
}

.input-room-inner {
	flex: 1;
	min-width: 0;
	height: 88rpx;
	line-height: 88rpx;
	padding: 0 20rpx;
	font-size: 34rpx;
	letter-spacing: 6rpx;
	font-weight: 600;
	background: transparent;
	border: none;
	box-sizing: border-box;
}

.room-input-divider {
	width: 2rpx;
	height: 48rpx;
	background: #ddd;
	flex-shrink: 0;
}

.btn-scan-inline {
	flex-shrink: 0;
	height: 88rpx;
	line-height: 88rpx;
	padding: 0 26rpx;
	margin: 0;
	font-size: 28rpx;
	color: #f33e54;
	font-weight: 600;
	background: transparent;
	border: none;
	border-radius: 0;
}

.btn-scan-inline::after {
	border: none;
}

.btn-scan-inline--hover {
	opacity: 0.75;
}

.status-row {
	margin-top: 24rpx;
	padding-top: 20rpx;
	border-top: 1rpx solid #eee;
}

.status {
	flex: 1;
	font-size: 26rpx;
	color: #888;
	margin-right: 16rpx;
}

.status--connected {
	color: #07c160;
	font-weight: 500;
}

.status--connecting {
	color: #1989fa;
}

.status--error {
	color: #ee0a24;
}

.btn-connect {
	flex-shrink: 0;
	background: #f33e54 !important;
}

.card-tools-pad {
	padding-top: 24rpx;
}

.main-tab-bar {
	display: flex;
	flex-direction: row;
	background: #f0f0f0;
	border-radius: 12rpx;
	padding: 6rpx;
	margin-bottom: 24rpx;
	gap: 6rpx;
}

.main-tab {
	flex: 1;
	text-align: center;
	font-size: 28rpx;
	color: #666;
	padding: 18rpx 12rpx;
	border-radius: 10rpx;
	transition: background 0.15s ease;
}

.main-tab--active {
	background: #fff;
	color: #f33e54;
	font-weight: 600;
	box-shadow: 0 2rpx 12rpx rgba(0, 0, 0, 0.06);
}

.tools-panel {
	padding-top: 0;
}

.tools-hint {
	display: block;
	font-size: 22rpx;
	color: #999;
	line-height: 1.45;
	margin-bottom: 20rpx;
}

.important-tools-grid {
	display: grid;
	grid-template-columns: 1fr 1fr 1fr;
	grid-template-rows: minmax(132rpx, auto) minmax(152rpx, auto) minmax(132rpx, auto);
	gap: 14rpx;
	margin-bottom: 8rpx;
}

.imp-slot {
	display: flex;
	align-items: stretch;
	justify-content: stretch;
	min-height: 0;
}

.imp-tl {
	grid-column: 1;
	grid-row: 1;
}

.imp-tr {
	grid-column: 3;
	grid-row: 1;
}

.imp-mid {
	grid-column: 2;
	grid-row: 2;
	align-self: center;
	justify-self: center;
	width: 200rpx;
}

.imp-bl {
	grid-column: 1;
	grid-row: 3;
}

.imp-br {
	grid-column: 3;
	grid-row: 3;
}

.imp-btn {
	width: 100%;
	min-height: 132rpx;
	padding: 16rpx 10rpx;
	margin: 0;
	display: flex;
	flex-direction: column;
	align-items: center;
	justify-content: center;
	gap: 8rpx;
	background-color: #f8f8f8;
	color: #333;
	border-radius: 14rpx;
	border: none;
	box-sizing: border-box;
	transition: transform 0.08s ease, opacity 0.08s ease;
}

.imp-btn:not(.imp-btn--center) {
	background-image: url('/static/36.png');
	background-size: 100% 100%;
	background-repeat: no-repeat;
}

.imp-btn--center {
	width: 200rpx;
	height: 200rpx;
	min-height: 200rpx;
	border-radius: 1000rpx;
	margin: 0 auto;
	padding: 12rpx;
	box-sizing: border-box;
	background-image: url('/static/img/45.png');
	background-size: 100% 100%;
	background-repeat: no-repeat;
}

.imp-btn::after {
	border: none;
}

.imp-btn--accent {
	background-color: transparent;
	color: #fff;
}

.imp-btn--accent:not(.imp-btn--center) {
	background-image: url('/static/36.png'), linear-gradient(145deg, #ff5a6a, #f33e54);
	background-size: 100% 100%, 100% 100%;
	background-repeat: no-repeat;
}

.imp-btn--accent.imp-btn--center {
	background-image: url('/static/img/45.png'), linear-gradient(145deg, #ff5a6a, #f33e54);
	background-size: 100% 100%, 100% 100%;
	background-repeat: no-repeat;
}

.imp-btn[disabled] {
	opacity: 0.42;
}

.imp-btn--offline {
	box-shadow: none;
}

.imp-btn--offline.imp-btn--accent {
	box-shadow: none;
}

.imp-btn--offline[disabled] {
	opacity: 0.58;
}

.tool-press-none {
	opacity: 1;
	transform: none;
}

.imp-press {
	transform: scale(0.97);
}

.imp-icon {
	display: flex;
	align-items: center;
	justify-content: center;
	margin-bottom: 4rpx;
	opacity: 0.9;
}

.imp-icon--lg {
	opacity: 1;
}

.imp-label {
	font-size: 22rpx;
	line-height: 1.25;
	text-align: center;
	display: -webkit-box;
	-webkit-box-orient: vertical;
	-webkit-line-clamp: 2;
	line-clamp: 2;
	overflow: hidden;
	word-break: break-all;
	padding: 0 4rpx;
	text-shadow: 1rpx 2rpx 3rpx rgba(0, 0, 0, 0.12);
}

.imp-btn--accent .imp-icon,
.imp-btn--accent .imp-label {
	text-shadow: 0 1rpx 2rpx rgba(0, 0, 0, 0.45);
}

.nine-block {
	margin-top: 28rpx;
	padding-top: 24rpx;
	border-top: 1rpx solid #f0f0f0;
}

.nine-block--under-pad {
	margin-top: 32rpx;
}

.nine-block-title {
	display: block;
	font-size: 26rpx;
	font-weight: 600;
	color: #333;
	margin-bottom: 16rpx;
}

.nine-grid {
	display: grid;
	grid-template-columns: repeat(3, 1fr);
	gap: 14rpx;
}

.nine-cell {
	margin: 0;
	padding: 18rpx 8rpx;
	min-height: 128rpx;
	display: flex;
	flex-direction: column;
	align-items: center;
	justify-content: center;
	gap: 10rpx;
	background-color: #f8f8f8;
	background-image: url('/static/36.png');
	background-size: 100% 100%;
	background-repeat: no-repeat;
	color: #333;
	border-radius: 14rpx;
	border: none;
	box-sizing: border-box;
	transition: transform 0.08s ease, opacity 0.08s ease;
}

.nine-cell::after {
	border: none;
}

.nine-cell--accent {
	background-color: transparent;
	color: #fff;
	background-image: url('/static/36.png'), linear-gradient(145deg, #ff5a6a, #f33e54);
	background-size: 100% 100%, 100% 100%;
	background-repeat: no-repeat;
}

.nine-cell[disabled] {
	opacity: 0.42;
}

.nine-cell--offline {
	box-shadow: none;
}

.nine-cell--offline.nine-cell--accent {
	box-shadow: none;
}

.nine-cell--offline[disabled] {
	opacity: 0.58;
}

.nine-press {
	transform: scale(0.97);
}

.nine-icon {
	display: flex;
	align-items: center;
	justify-content: center;
	margin-bottom: 4rpx;
	opacity: 0.88;
}

.nine-label {
	font-size: 22rpx;
	line-height: 1.25;
	text-align: center;
	display: -webkit-box;
	-webkit-box-orient: vertical;
	-webkit-line-clamp: 2;
	line-clamp: 2;
	overflow: hidden;
	word-break: break-all;
	text-shadow: 1rpx 2rpx 3rpx rgba(0, 0, 0, 0.12);
}

.nine-cell--accent .nine-icon,
.nine-cell--accent .nine-label {
	text-shadow: 0 1rpx 2rpx rgba(0, 0, 0, 0.45);
}

.pad-panel {
	padding-top: 4rpx;
}

.laser-pad {
	position: relative;
	height: 280rpx;
	background: linear-gradient(145deg, #2c2c2c, #1a1a1a);
	border-radius: 12rpx;
	display: flex;
	align-items: center;
	justify-content: center;
	touch-action: none;
}

.laser-pad.ppt-notes-laser-pad {
	height: 240rpx;
	min-height: 240rpx;
}

.laser-hint {
	font-size: 24rpx;
	color: rgba(255, 255, 255, 0.45);
	pointer-events: none;
	text-align: center;
	padding: 0 16rpx;
}

.laser-subhint {
	display: block;
	font-size: 22rpx;
	color: #999;
	margin-top: 12rpx;
	line-height: 1.4;
}

.modal-mask {
	position: fixed;
	left: 0;
	right: 0;
	top: 0;
	bottom: 0;
	background: rgba(0, 0, 0, 0.45);
	z-index: 1000;
	display: flex;
	align-items: center;
	justify-content: center;
	padding: 40rpx;
	box-sizing: border-box;
}

.modal-box {
	width: 100%;
	max-width: 640rpx;
	background: #fff;
	border-radius: 16rpx;
	padding: 32rpx;
	box-sizing: border-box;
}

.modal-title {
	display: block;
	font-size: 32rpx;
	font-weight: 600;
	color: #333;
	margin-bottom: 24rpx;
}

.modal-input {
	width: 100%;
	min-height: 160rpx;
	padding: 20rpx;
	font-size: 28rpx;
	background: #f5f5f5;
	border-radius: 12rpx;
	box-sizing: border-box;
	margin-bottom: 28rpx;
}

.modal-btns {
	display: flex;
	gap: 20rpx;
}

.modal-btn {
	flex: 1;
	height: 80rpx;
	line-height: 80rpx;
	font-size: 28rpx;
}

.modal-btn::after {
	border: none;
}

.modal-btn-cancel {
	background: #f0f0f0;
	color: #333;
}

.modal-box--settings {
	max-width: 600rpx;
}

.settings-hint {
	display: block;
	font-size: 24rpx;
	color: #999;
	line-height: 1.45;
	margin-bottom: 28rpx;
}

.settings-rows {
	margin-bottom: 32rpx;
}

.settings-row {
	display: flex;
	flex-direction: row;
	align-items: center;
	justify-content: space-between;
	padding: 24rpx 0;
	border-bottom: 1rpx solid #f0f0f0;
}

.settings-row:last-child {
	border-bottom: none;
}

.room-expired-hint {
	display: flex;
	align-items: center;
	justify-content: space-between;
	margin-top: 16rpx;
	padding: 16rpx 20rpx;
	background: #fff8e1;
	border-radius: 10rpx;
	border: 1rpx solid #ffe082;
}

.room-expired-text {
	font-size: 24rpx;
	color: #e65100;
	flex: 1;
	margin-right: 16rpx;
	line-height: 1.4;
}

.btn-rescan {
	font-size: 24rpx;
	color: #fff;
	background: #f33e54 !important;
	border-radius: 8rpx;
	padding: 0 20rpx;
	height: 56rpx;
	line-height: 56rpx;
	flex-shrink: 0;
}

.btn-rescan::after {
	border: none;
}

.settings-row--col {
	flex-direction: column;
	align-items: stretch;
	padding-top: 4rpx;
	padding-bottom: 12rpx;
}

.settings-row--col .settings-row {
	border-bottom: none;
	padding: 0;
}

.settings-sub-hint {
	display: block;
	font-size: 22rpx;
	color: #f39800;
	line-height: 1.5;
	margin-top: 8rpx;
}

.settings-label {
	flex: 1;
	font-size: 28rpx;
	color: #333;
	padding-right: 24rpx;
	line-height: 1.4;
}

.settings-done-btn {
	width: 100%;
	height: 80rpx;
	line-height: 80rpx;
	font-size: 28rpx;
	background: #f33e54 !important;
	color: #fff !important;
	border-radius: 12rpx;
	margin: 0;
}

.settings-done-btn::after {
	border: none;
}

.modal-box--spotlight {
	max-width: 620rpx;
}

.spotlight-header {
	display: flex;
	flex-direction: row;
	align-items: center;
	justify-content: space-between;
	margin-bottom: 16rpx;
}

.spotlight-header-title {
	flex: 1;
	font-size: 32rpx;
	font-weight: 600;
	color: #333;
	padding-right: 16rpx;
}

.spotlight-close {
	width: 64rpx;
	height: 64rpx;
	margin: -8rpx -8rpx -8rpx 0;
	display: flex;
	align-items: center;
	justify-content: center;
	flex-shrink: 0;
}

.spotlight-close--pressed {
	opacity: 0.55;
}

.spotlight-close-x {
	width: 32rpx;
	height: 32rpx;
	position: relative;
}

.spotlight-close-line {
	position: absolute;
	left: 50%;
	top: 50%;
	width: 32rpx;
	height: 4rpx;
	background: #555;
	border-radius: 2rpx;
	margin-left: -16rpx;
	margin-top: -2rpx;
	transform: rotate(45deg);
}

.spotlight-close-line--r {
	transform: rotate(-45deg);
}

.spotlight-pad-wrap {
	width: 100%;
	position: relative;
	padding-bottom: 100%;
	height: 0;
	margin-bottom: 8rpx;
}

.spotlight-switch-row {
	margin-bottom: 8rpx;
}

.spotlight-size-label {
	display: block;
	font-size: 26rpx;
	color: #555;
	margin: 16rpx 0 8rpx;
}

.spotlight-slider {
	margin: 0 0 20rpx;
}

.spotlight-pad {
	position: absolute;
	left: 0;
	top: 0;
	width: 100%;
	height: 100%;
	background: linear-gradient(145deg, #2a2a2a, #181818);
	border-radius: 12rpx;
	display: flex;
	align-items: center;
	justify-content: center;
	touch-action: none;
	box-sizing: border-box;
}

.spotlight-pad-hint {
	font-size: 24rpx;
	color: rgba(255, 255, 255, 0.45);
	text-align: center;
	padding: 0 20rpx;
	pointer-events: none;
}
</style>
