import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import './style.css'
import './workspace.css'
import './creation.css'

const app = createApp(App)
const pinia = createPinia()

// Toast 插件
const toastInstance = {
  component: null,
  success: () => {},
  error: () => {},
  warning: () => {},
  info: () => {},
}

// Confirm 插件
const confirmInstance = {
  component: null,
  show: () => Promise.resolve(false),
  close: () => {},
}

app.config.globalProperties.$toast = toastInstance
app.config.globalProperties.$loading = null
app.config.globalProperties.$confirm = confirmInstance

app.use(pinia)

// 挂载应用
const vm = app.mount('#app')

// 注入 Toast、Loading 和 Confirm 实例
if (vm.$refs.toast) {
  toastInstance.component = vm.$refs.toast
  toastInstance.success = vm.$refs.toast.success
  toastInstance.error = vm.$refs.toast.error
  toastInstance.warning = vm.$refs.toast.warning
  toastInstance.info = vm.$refs.toast.info
}

if (vm.$refs.loading) {
  app.config.globalProperties.$loading = vm.$refs.loading
}

if (vm.$refs.confirm) {
  confirmInstance.component = vm.$refs.confirm
  confirmInstance.show = vm.$refs.confirm.show
  confirmInstance.close = vm.$refs.confirm.close
}
