<template>
	<view class="page">
		<view class="user-card card" @click="onUserCardTap">
			<image
				v-if="profile && profile.avatarUrl"
				class="user-avatar"
				:src="profile.avatarUrl"
				mode="aspectFill"
			/>
			<view v-else class="user-avatar user-avatar--placeholder">
				<ppt-icon name="user" :size="44" color="#f33e54" />
			</view>
			<view class="user-info">
				<text class="user-name">{{ profile ? profile.nickName || '微信用户' : '点击登录' }}</text>
				<text class="user-hint">{{ profile ? '已展示本地头像昵称' : '使用微信头像与昵称（仅保存在本机）' }}</text>
			</view>
			<text v-if="profile" class="user-logout" @click.stop="onLogout">退出</text>
		</view>

		<view class="card menu-card">
			<view class="menu-row" @click="goPage('/pages/me/manual')">
				<view class="menu-icon menu-icon--book">
					<ppt-icon name="book-open" :size="32" color="#1976d2" />
				</view>
				<text class="menu-title">操作手册</text>
				<text class="menu-arrow">›</text>
			</view>
			<view class="menu-row" @click="onClearCache">
				<view class="menu-icon menu-icon--cache">
					<ppt-icon name="trash-2" :size="32" color="#e65100" />
				</view>
				<text class="menu-title">清除缓存</text>
				<text class="menu-arrow">›</text>
			</view>
			<view class="menu-row" @click="goPage('/pages/me/privacy')">
				<view class="menu-icon menu-icon--shield">
					<ppt-icon name="shield" :size="32" color="#3949ab" />
				</view>
				<text class="menu-title">隐私协议</text>
				<text class="menu-arrow">›</text>
			</view>
			<view class="menu-row" @click="goPage('/pages/me/agreement')">
				<view class="menu-icon menu-icon--doc">
					<ppt-icon name="file-text" :size="32" color="#388e3c" />
				</view>
				<text class="menu-title">用户协议</text>
				<text class="menu-arrow">›</text>
			</view>
			<!-- #ifdef MP-WEIXIN -->
			<button class="menu-row menu-row--btn" open-type="contact" hover-class="menu-row--hover">
				<view class="menu-icon menu-icon--service">
					<ppt-icon name="message-circle" :size="32" color="#c2185b" />
				</view>
				<text class="menu-title">我的客服</text>
				<text class="menu-arrow">›</text>
			</button>
			<!-- #endif -->
			<!-- #ifndef MP-WEIXIN -->
			<view class="menu-row" @click="onContactUnavailable">
				<view class="menu-icon menu-icon--service">
					<ppt-icon name="message-circle" :size="32" color="#c2185b" />
				</view>
				<text class="menu-title">我的客服</text>
				<text class="menu-arrow">›</text>
			</view>
			<!-- #endif -->
			<view class="menu-row" @click="goPage('/pages/timer/timer')">
				<view class="menu-icon menu-icon--timer">
					<ppt-icon name="timer" :size="32" color="#0288d1" />
				</view>
				<text class="menu-title">计时器</text>
				<text class="menu-arrow">›</text>
			</view>
			<view class="menu-row menu-row--last" @click="goPage('/pages/me/about')">
				<view class="menu-icon menu-icon--info">
					<ppt-icon name="info" :size="32" color="#757575" />
				</view>
				<text class="menu-title">关于我们</text>
				<text class="menu-arrow">›</text>
			</view>
		</view>
	</view>
</template>

<script>
import { clearOptionalCache, STORAGE_USER_PROFILE } from '../../../common/uploadRoomFile.js';
import PptIcon from '../../../components/ppt-icon/ppt-icon.vue';

export default {
	components: { PptIcon },
	data() {
		return {
			profile: null
		};
	},
	onShow() {
		this.loadProfile();
	},
	methods: {
		loadProfile() {
			try {
				const raw = uni.getStorageSync(STORAGE_USER_PROFILE);
				if (!raw) {
					this.profile = null;
					return;
				}
				const p = typeof raw === 'string' ? JSON.parse(raw) : raw;
				this.profile = p && (p.nickName || p.avatarUrl) ? p : null;
			} catch (e) {
				this.profile = null;
			}
		},
		saveProfile(p) {
			try {
				uni.setStorageSync(STORAGE_USER_PROFILE, JSON.stringify(p));
			} catch (e) {
				// ignore
			}
			this.profile = p;
		},
		onUserCardTap() {
			if (this.profile) return;
			// #ifdef MP-WEIXIN
			uni.getUserProfile({
				desc: '用于在个人中心展示头像与昵称',
				success: (res) => {
					const u = res.userInfo || {};
					this.saveProfile({
						nickName: u.nickName || '',
						avatarUrl: u.avatarUrl || ''
					});
					uni.showToast({ title: '已保存到本机', icon: 'success' });
				},
				fail: () => {
					uni.showToast({ title: '需要授权才能展示资料', icon: 'none' });
				}
			});
			// #endif
			// #ifndef MP-WEIXIN
			uni.showToast({ title: '请在微信小程序中使用', icon: 'none' });
			// #endif
		},
		onLogout() {
			uni.showModal({
				title: '退出登录',
				content: '将清除本机保存的头像与昵称展示信息。',
				confirmColor: '#f33e54',
				success: (res) => {
					if (res.confirm) {
						try {
							uni.removeStorageSync(STORAGE_USER_PROFILE);
						} catch (e) {
							// ignore
						}
						this.profile = null;
						uni.showToast({ title: '已退出', icon: 'none' });
					}
				}
			});
		},
		goPage(url) {
			uni.navigateTo({ url });
		},
		onClearCache() {
			uni.showModal({
				title: '清除缓存',
				content: '将清除发送记录与本地登录展示信息，不会清除房间号与常用功能排序。',
				confirmColor: '#f33e54',
				success: (res) => {
					if (res.confirm) {
						clearOptionalCache();
						this.profile = null;
						uni.showToast({ title: '已清除', icon: 'success' });
					}
				}
			});
		},
		onContactUnavailable() {
			uni.showToast({ title: '请在微信小程序中使用客服', icon: 'none' });
		}
	}
};
</script>

<style scoped>
.page {
	min-height: 100vh;
	padding: 24rpx;
	padding-bottom: 48rpx;
	background: #f0f0f0;
	box-sizing: border-box;
}

.card {
	background: #fff;
	border-radius: 16rpx;
	padding: 28rpx;
	margin-bottom: 24rpx;
	box-shadow: 0 4rpx 24rpx rgba(0, 0, 0, 0.06);
	box-sizing: border-box;
}

.user-card {
	display: flex;
	flex-direction: row;
	align-items: center;
	gap: 24rpx;
	padding: 32rpx 28rpx;
}

.user-avatar {
	width: 112rpx;
	height: 112rpx;
	border-radius: 50%;
	flex-shrink: 0;
	background: #eee;
}

.user-avatar--placeholder {
	display: flex;
	align-items: center;
	justify-content: center;
	background: linear-gradient(145deg, #ffe4e8, #ffd0d8);
}

.user-avatar-ph {
	display: flex;
	align-items: center;
	justify-content: center;
	width: 100%;
	height: 100%;
}

.user-info {
	flex: 1;
	min-width: 0;
}

.user-name {
	display: block;
	font-size: 34rpx;
	font-weight: 600;
	color: #333;
	margin-bottom: 8rpx;
}

.user-hint {
	display: block;
	font-size: 24rpx;
	color: #999;
	line-height: 1.4;
}

.user-logout {
	font-size: 26rpx;
	color: #f33e54;
	flex-shrink: 0;
	padding: 8rpx 0 8rpx 16rpx;
}

.menu-card {
	padding: 0 28rpx;
	overflow: hidden;
}

.menu-row {
	display: flex;
	flex-direction: row;
	align-items: center;
	min-height: 104rpx;
	border-bottom: 1rpx solid #f0f0f0;
	padding: 16rpx 0;
	box-sizing: border-box;
}

.menu-row--last {
	border-bottom: none;
}

.menu-row--btn {
	margin: 0;
	padding-left: 0;
	padding-right: 0;
	background: transparent;
	line-height: inherit;
	text-align: left;
	font-size: inherit;
	border-radius: 0;
	border-bottom: 1rpx solid #f0f0f0;
}

.menu-row--btn::after {
	border: none;
}

.menu-row--hover {
	opacity: 0.85;
}

.menu-icon {
	width: 64rpx;
	height: 64rpx;
	border-radius: 16rpx;
	display: flex;
	align-items: center;
	justify-content: center;
	font-size: 32rpx;
	margin-right: 20rpx;
	flex-shrink: 0;
}

.menu-icon--book {
	background: linear-gradient(145deg, #e3f2fd, #bbdefb);
}

.menu-icon--cache {
	background: linear-gradient(145deg, #fff3e0, #ffe0b2);
}

.menu-icon--shield {
	background: linear-gradient(145deg, #e8eaf6, #c5cae9);
}

.menu-icon--doc {
	background: linear-gradient(145deg, #e8f5e9, #c8e6c9);
}

.menu-icon--service {
	background: linear-gradient(145deg, #fce4ec, #f8bbd9);
}

.menu-icon--timer {
	background: linear-gradient(145deg, #e1f5fe, #b3e5fc);
}

.menu-icon--info {
	background: linear-gradient(145deg, #f5f5f5, #eeeeee);
}

.menu-title {
	flex: 1;
	font-size: 30rpx;
	color: #333;
}

.menu-arrow {
	font-size: 36rpx;
	color: #ccc;
	font-weight: 300;
	flex-shrink: 0;
	margin-left: 12rpx;
}
</style>
