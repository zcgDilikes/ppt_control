<template>
	<view class="page">
		<view class="card mode-card">
			<text class="section-title">模式</text>
			<view class="mode-row">
				<button
					class="mode-btn"
					:class="{ 'mode-btn--active': mode === 'countdown' }"
					@click="setMode('countdown')"
				>
					倒计时
				</button>
				<button
					class="mode-btn"
					:class="{ 'mode-btn--active': mode === 'stopwatch' }"
					@click="setMode('stopwatch')"
				>
					正计时
				</button>
			</view>
		</view>

		<view v-if="mode === 'countdown'" class="card">
			<text class="section-title">倒计时时长（分钟）</text>
			<view class="minute-row">
				<button class="mini-btn" :disabled="running || minutes <= 1" @click="adjustMinutes(-1)">−</button>
				<text class="minute-val">{{ minutes }}</text>
				<button class="mini-btn" :disabled="running || minutes >= 180" @click="adjustMinutes(1)">+</button>
			</view>
		</view>

		<view class="card display-card">
			<text class="clock">{{ displayText }}</text>
			<text class="state-hint">{{ stateHint }}</text>
		</view>

		<view class="card">
			<view class="row-sync">
				<text class="sync-label">大屏显示（投影可见）</text>
				<switch :checked="mirrorPc" color="#f33e54" :disabled="!canMirror" @change="onMirrorChange" />
			</view>
			<text class="sync-hint">手机为主控端，PC 大屏仅做镜像显示。需首页已连接且 PC 端就绪；开始/暂停/重置时同步到大屏，走时以手机为准。</text>
		</view>

		<view class="btn-row">
			<button v-if="!running || paused" class="btn-main" type="primary" @click="onStartOrResume">
				{{ running && paused ? '继续' : '开始' }}
			</button>
			<button v-if="running && !paused" class="btn-secondary" @click="onPause">暂停</button>
			<button class="btn-secondary" @click="onReset">重置</button>
		</view>
	</view>
</template>

<script>
import { WS_STATUS } from '../../utils/pptSocket.js';

export default {
	data() {
		return {
			mode: 'countdown',
			minutes: 5,
			secondsLeft: 300,
			elapsed: 0,
			running: false,
			paused: false,
			tickTimer: null,
			mirrorPc: false,
			/** 与 globalData 同步，便于 onShow 刷新开关可用态 */
			mirrorChannelOk: false
		};
	},
	computed: {
		displayText() {
			const s = this.mode === 'countdown' ? this.secondsLeft : this.elapsed;
			return this._formatClock(s);
		},
		stateHint() {
			if (!this.running) return '未开始';
			return this.paused ? '已暂停' : '进行中';
		},
		canMirror() {
			return this.mirrorChannelOk;
		}
	},
	onShow() {
		this.refreshMirrorChannel();
	},
	onUnload() {
		this._clearTick();
		if (this.mirrorPc) this._sendPc('TIMER_OVERLAY_HIDE');
	},
	methods: {
		refreshMirrorChannel() {
			try {
				const app = getApp();
				const s = app.globalData.pptSocket;
				this.mirrorChannelOk = !!(
					s &&
					s.getStatus &&
					s.getStatus() === WS_STATUS.CONNECTED &&
					app.globalData.peerPcOnline
				);
			} catch (e) {
				this.mirrorChannelOk = false;
			}
			if (!this.mirrorChannelOk && this.mirrorPc) {
				this.mirrorPc = false;
			}
		},
		_formatClock(totalSec) {
			const s = Math.max(0, Math.floor(totalSec));
			const h = Math.floor(s / 3600);
			const m = Math.floor((s % 3600) / 60);
			const sec = s % 60;
			if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`;
			return `${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`;
		},
		setMode(m) {
			if (this.running) return;
			this.mode = m;
			if (m === 'countdown') {
				this.secondsLeft = Math.max(1, this.minutes) * 60;
				this.elapsed = 0;
			} else {
				this.elapsed = 0;
			}
		},
		adjustMinutes(d) {
			if (this.running) return;
			const n = Math.min(180, Math.max(1, this.minutes + d));
			this.minutes = n;
			this.secondsLeft = n * 60;
		},
		onMirrorChange(e) {
			this.refreshMirrorChannel();
			const want = !!(e.detail && e.detail.value);
			if (want && !this.mirrorChannelOk) {
				this.mirrorPc = false;
				uni.showToast({ title: '请先连接并完成配对', icon: 'none' });
				return;
			}
			this.mirrorPc = want;
			if (!this.mirrorPc) {
				this._sendPc('TIMER_OVERLAY_HIDE');
			}
		},
		_getSocket() {
			try {
				const app = getApp();
				const s = app.globalData.pptSocket;
				if (s && s.getStatus && s.getStatus() === WS_STATUS.CONNECTED && app.globalData.peerPcOnline) {
					return s;
				}
			} catch (e) {
				// ignore
			}
			return null;
		},
		_sendPc(cmd, payload) {
			const s = this._getSocket();
			if (!s) return;
			const o = payload || {};
			s.sendCmd(cmd, o).catch(() => {});
		},
		onStartOrResume() {
			if (!this.running) {
				if (this.mode === 'countdown') {
					this.secondsLeft = Math.max(1, this.minutes) * 60;
				} else {
					this.elapsed = 0;
				}
				this.running = true;
				this.paused = false;
				this._startTick();
				if (this.mirrorPc && this.canMirror) {
					const sec = this.mode === 'countdown' ? this.secondsLeft : 0;
					this._sendPc('TIMER_OVERLAY_SHOW', { mode: this.mode, seconds: sec });
				}
				return;
			}
			if (this.paused) {
				this.paused = false;
				this._startTick();
				if (this.mirrorPc) this._sendPc('TIMER_OVERLAY_RESUME');
			}
		},
		onPause() {
			if (!this.running || this.paused) return;
			this.paused = true;
			this._clearTick();
			if (this.mirrorPc) this._sendPc('TIMER_OVERLAY_PAUSE');
		},
		onReset() {
			this._clearTick();
			this.running = false;
			this.paused = false;
			if (this.mode === 'countdown') {
				this.secondsLeft = Math.max(1, this.minutes) * 60;
			} else {
				this.elapsed = 0;
			}
			if (this.mirrorPc) {
				const sec = this.mode === 'countdown' ? this.secondsLeft : 0;
				this._sendPc('TIMER_OVERLAY_RESET', { seconds: sec });
			}
		},
		_startTick() {
			this._clearTick();
			this.tickTimer = setInterval(() => this._tick(), 1000);
		},
		_clearTick() {
			if (this.tickTimer != null) {
				clearInterval(this.tickTimer);
				this.tickTimer = null;
			}
		},
		_tick() {
			if (!this.running || this.paused) return;
			if (this.mode === 'countdown') {
				this.secondsLeft -= 1;
				if (this.secondsLeft <= 0) {
					this.secondsLeft = 0;
					this.running = false;
					this.paused = false;
					this._clearTick();
					// #ifdef MP-WEIXIN
					try {
						uni.vibrateLong({});
					} catch (e1) {
						uni.vibrateShort({});
					}
					// #endif
					uni.showToast({ title: '时间到', icon: 'none' });
					if (this.mirrorPc) this._sendPc('TIMER_OVERLAY_HIDE');
				}
			} else {
				this.elapsed += 1;
			}
		}
	}
};
</script>

<style scoped>
.page {
	min-height: 100vh;
	background: #f0f0f0;
	padding: 24rpx;
	box-sizing: border-box;
	padding-bottom: 48rpx;
}

.card {
	background: #fff;
	border-radius:16rpx;
	padding: 28rpx;
	margin-bottom: 24rpx;
	box-shadow: 0 4rpx 24rpx rgba(0, 0, 0, 0.06);
}

.section-title {
	display: block;
	font-size: 28rpx;
	font-weight: 600;
	color: #333;
	margin-bottom: 20rpx;
}

.mode-row {
	display: flex;
	gap: 20rpx;
}

.mode-btn {
	flex: 1;
	height: 72rpx;
	line-height: 72rpx;
	font-size: 28rpx;
	background: #f0f0f0;
	color: #666;
	border: none;
	border-radius: 12rpx;
	margin: 0;
}

.mode-btn--active {
	background: linear-gradient(145deg, #ff5a6a, #f33e54);
	color: #fff;
	font-weight: 600;
}

.mode-btn::after {
	border: none;
}

.minute-row {
	display: flex;
	align-items: center;
	justify-content: center;
	gap: 40rpx;
}

.minute-val {
	font-size: 56rpx;
	font-weight: 700;
	color: #333;
	min-width: 100rpx;
	text-align: center;
}

.mini-btn {
	width: 80rpx;
	height: 80rpx;
	line-height: 80rpx;
	padding: 0;
	margin: 0;
	font-size: 40rpx;
	background: #f5f5f5;
	border-radius: 12rpx;
	border: none;
}

.mini-btn::after {
	border: none;
}

.display-card {
	text-align: center;
	padding: 40rpx 28rpx;
}

.clock {
	font-size: 88rpx;
	font-weight: 700;
	font-variant-numeric: tabular-nums;
	color: #1a1a1a;
	letter-spacing: 4rpx;
}

.state-hint {
	display: block;
	margin-top: 16rpx;
	font-size: 26rpx;
	color: #888;
}

.row-sync {
	display: flex;
	align-items: center;
	justify-content: space-between;
}

.sync-label {
	font-size: 28rpx;
	color: #333;
}

.sync-hint {
	display: block;
	margin-top: 16rpx;
	font-size: 22rpx;
	color: #999;
	line-height: 1.45;
}

.btn-row {
	display: flex;
	flex-direction: column;
	gap: 20rpx;
	margin-top: 8rpx;
}

.btn-main {
	background: #f33e54 !important;
	color: #fff !important;
	border-radius: 12rpx;
	height: 88rpx;
	line-height: 88rpx;
	font-size: 30rpx;
}

.btn-main::after {
	border: none;
}

.btn-secondary {
	background: #fff;
	color: #333;
	border: 2rpx solid #ddd;
	border-radius: 12rpx;
	height: 80rpx;
	line-height: 80rpx;
	font-size: 28rpx;
}

.btn-secondary::after {
	border: none;
}
</style>
