<template>
  <div v-if="hasHomeContent" class="min-h-screen">
    <iframe
      v-if="isHomeContentUrl"
      :src="homeContent.trim()"
      class="h-screen w-full border-0"
      allowfullscreen
    ></iframe>
    <!-- homeContent is an admin-only setting. -->
    <div v-else v-html="homeContent"></div>
  </div>

  <div
    v-else-if="compactHomeEnabled"
    data-testid="compact-home"
    class="flex min-h-screen flex-col bg-gray-50 text-gray-900 dark:bg-dark-950 dark:text-white"
  >
    <header class="border-b border-gray-200 px-4 py-4 sm:px-6 dark:border-dark-800">
      <nav class="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-3 sm:gap-4">
        <div class="flex min-w-0 flex-1 items-center gap-3">
          <img
            :src="siteLogo || '/logo.png'"
            alt="Logo"
            class="h-9 w-9 shrink-0 rounded-lg object-cover"
          />
          <span class="min-w-0 truncate text-base font-semibold">{{ siteName }}</span>
        </div>
        <div class="flex max-w-full shrink-0 flex-wrap items-center justify-end gap-2">
          <LocaleSwitcher />
          <a
            v-if="docUrl"
            :href="docUrl"
            target="_blank"
            rel="noopener noreferrer"
            class="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-gray-500 hover:bg-gray-100 dark:text-dark-400 dark:hover:bg-dark-800"
            :title="t('home.viewDocs')"
          >
            <Icon name="book" size="md" />
          </a>
          <button
            class="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-gray-500 hover:bg-gray-100 dark:text-dark-400 dark:hover:bg-dark-800"
            :title="isDark ? t('home.switchToLight') : t('home.switchToDark')"
            @click="toggleTheme"
          >
            <Icon v-if="isDark" name="sun" size="md" />
            <Icon v-else name="moon" size="md" />
          </button>
          <router-link
            :to="isAuthenticated ? dashboardPath : '/login'"
            class="inline-flex min-h-10 shrink-0 items-center justify-center rounded-lg bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-800 dark:bg-white dark:text-gray-900 dark:hover:bg-gray-200"
          >
            {{ isAuthenticated ? t('home.dashboard') : t('home.login') }}
          </router-link>
        </div>
      </nav>
    </header>

    <main class="flex min-w-0 flex-1 items-center justify-center px-4 py-16 sm:px-6">
      <div class="min-w-0 max-w-2xl text-center">
        <img
          :src="siteLogo || '/logo.png'"
          alt="Logo"
          class="mx-auto mb-6 h-20 w-20 rounded-lg object-cover"
        />
        <h1 class="[overflow-wrap:anywhere] text-3xl font-bold md:text-4xl">{{ siteName }}</h1>
        <p class="mt-4 whitespace-pre-wrap [overflow-wrap:anywhere] text-base text-gray-600 dark:text-dark-300">
          {{ siteSubtitle }}
        </p>
        <router-link
          :to="isAuthenticated ? dashboardPath : '/login'"
          class="mt-8 inline-flex min-h-10 items-center justify-center rounded-lg bg-primary-600 px-5 py-2.5 text-sm font-medium text-white hover:bg-primary-700"
        >
          {{ isAuthenticated ? t('home.goToDashboard') : t('home.login') }}
        </router-link>
      </div>
    </main>

    <footer class="min-w-0 border-t border-gray-200 px-4 py-5 text-center text-sm text-gray-500 [overflow-wrap:anywhere] sm:px-6 dark:border-dark-800 dark:text-dark-400">
      &copy; {{ currentYear }} {{ siteName }}
    </footer>
  </div>

  <div
    v-else
    data-testid="default-home"
    class="relative flex min-h-screen flex-col overflow-hidden bg-gray-50 text-gray-900 dark:bg-[#0d0c12] dark:text-white"
  >
    <div class="pointer-events-none absolute inset-0" aria-hidden="true">
      <div
        class="absolute inset-y-0 left-1/2 w-[min(48rem,82vw)] -translate-x-1/2 border-x border-primary-100/70 dark:border-primary-950/40"
      ></div>
      <div class="absolute inset-x-0 top-1/2 border-t border-primary-100/70 dark:border-primary-950/40"></div>
    </div>

    <header class="relative z-10 px-4 py-4 sm:px-6 sm:py-6">
      <nav class="mx-auto flex max-w-6xl items-center justify-between">
        <div class="flex min-w-0 items-center gap-3">
          <img
            :src="siteLogo || '/logo.png'"
            alt="VSPLab Logo"
            class="h-9 w-9 shrink-0 rounded-lg border border-gray-200 object-cover dark:border-dark-700"
          />
          <span class="hidden truncate text-sm font-semibold sm:block">VSP Lab AI Gateway</span>
        </div>

        <div class="flex items-center gap-2">
          <LocaleSwitcher />
          <button
            class="flex h-10 w-10 items-center justify-center rounded-lg border border-gray-200 bg-white text-gray-500 hover:bg-gray-100 dark:border-dark-700 dark:bg-dark-900 dark:text-dark-300 dark:hover:bg-dark-800"
            :title="isDark ? t('home.switchToLight') : t('home.switchToDark')"
            @click="toggleTheme"
          >
            <Icon v-if="isDark" name="sun" size="md" />
            <Icon v-else name="moon" size="md" />
          </button>
          <router-link
            :to="isAuthenticated ? dashboardPath : '/login'"
            class="hidden min-h-10 items-center justify-center rounded-lg border border-gray-200 bg-white px-4 text-sm font-semibold text-gray-900 hover:bg-gray-100 sm:inline-flex dark:border-dark-700 dark:bg-dark-900 dark:text-white dark:hover:bg-dark-800"
          >
            {{ isAuthenticated ? t('home.dashboard') : t('home.login') }}
          </router-link>
        </div>
      </nav>
    </header>

    <main class="relative z-10 flex flex-1 items-center justify-center px-5 py-8 sm:px-6 sm:py-12">
      <section class="flex w-full max-w-3xl flex-col items-center text-center">
        <img
          data-testid="home-hero-logo"
          :src="siteLogo || '/logo.png'"
          alt="VSPLab Logo"
          class="h-28 w-28 rounded-lg border-2 border-white object-cover shadow-xl shadow-primary-900/10 sm:h-36 sm:w-36 dark:border-dark-800 dark:shadow-black/40"
        />
        <div class="mt-7 flex items-center gap-3 text-xs font-bold uppercase text-primary-500">
          <span class="h-px w-7 bg-primary-300 dark:bg-primary-700"></span>
          Research Infrastructure
          <span class="h-px w-7 bg-primary-300 dark:bg-primary-700"></span>
        </div>
        <h1 class="mt-4 text-4xl font-bold leading-tight sm:text-5xl lg:text-6xl">
          VSP Lab <span class="text-primary-600 dark:text-primary-400">AI Gateway</span>
        </h1>
        <p class="mt-5 max-w-xl text-base leading-7 text-gray-600 sm:text-lg dark:text-dark-300">
          VSPLab 专用 AI 模型网关，管理 VSPLab 的 AI 算力。
        </p>
        <div data-testid="home-primary-cta" class="mt-8">
          <router-link
            :to="isAuthenticated ? dashboardPath : '/login'"
            class="inline-flex min-h-12 items-center justify-center gap-2 rounded-lg bg-primary-600 px-6 text-sm font-semibold text-white shadow-lg shadow-primary-600/25 hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 dark:focus:ring-offset-[#0d0c12]"
          >
            {{ isAuthenticated ? '进入控制台' : t('home.login') }}
            <Icon name="arrowRight" size="sm" :stroke-width="2" />
          </router-link>
        </div>
      </section>
    </main>

    <footer class="relative z-10 border-t border-gray-200 px-5 py-5 text-center text-xs text-gray-500 dark:border-dark-800 dark:text-dark-400">
      <div class="flex flex-wrap items-center justify-center gap-x-2 gap-y-1">
        <span>
          Developed by
          <a
            :href="developerUrl"
            target="_blank"
            rel="noopener noreferrer"
            class="font-semibold text-gray-900 hover:text-primary-600 dark:text-white dark:hover:text-primary-400"
          >Hypoxanthine / 贺云翔</a>
        </span>
        <span class="text-cyan-500" aria-hidden="true">&bull;</span>
        <span>
          Forked from
          <a
            :href="upstreamUrl"
            target="_blank"
            rel="noopener noreferrer"
            class="font-semibold text-gray-900 hover:text-primary-600 dark:text-white dark:hover:text-primary-400"
          >Sub2API</a>
        </span>
      </div>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAppStore, useAuthStore } from '@/stores'
import LocaleSwitcher from '@/components/common/LocaleSwitcher.vue'
import Icon from '@/components/icons/Icon.vue'
import { sanitizeUrl } from '@/utils/url'

const { t } = useI18n()
const authStore = useAuthStore()
const appStore = useAppStore()

const siteName = computed(() => appStore.cachedPublicSettings?.site_name || appStore.siteName || 'Sub2API')
const siteLogo = computed(() =>
  sanitizeUrl(appStore.cachedPublicSettings?.site_logo || appStore.siteLogo || '', {
    allowRelative: true,
    allowDataUrl: true,
  })
)
const siteSubtitle = computed(() => appStore.cachedPublicSettings?.site_subtitle || 'AI API Gateway Platform')
const docUrl = computed(() => sanitizeUrl(appStore.cachedPublicSettings?.doc_url || appStore.docUrl || ''))
const homeContent = computed(() => appStore.cachedPublicSettings?.home_content || '')
const hasHomeContent = computed(() => homeContent.value.trim().length > 0)
const compactHomeEnabled = computed(() => appStore.cachedPublicSettings?.compact_home_enabled === true)
const isHomeContentUrl = computed(() => {
  const content = homeContent.value.trim()
  return content.startsWith('http://') || content.startsWith('https://')
})

const isDark = ref(document.documentElement.classList.contains('dark'))
const isAuthenticated = computed(() => authStore.isAuthenticated)
const isAdmin = computed(() => authStore.isAdmin)
const dashboardPath = computed(() => (isAdmin.value ? '/admin/dashboard' : '/dashboard'))
const currentYear = computed(() => new Date().getFullYear())
const developerUrl = 'https://github.com/HypoxanthineOvO'
const upstreamUrl = 'https://github.com/Wei-Shaw/sub2api'

function toggleTheme() {
  isDark.value = !isDark.value
  document.documentElement.classList.toggle('dark', isDark.value)
  localStorage.setItem('theme', isDark.value ? 'dark' : 'light')
}

function initTheme() {
  const savedTheme = localStorage.getItem('theme')
  if (
    savedTheme === 'dark' ||
    (!savedTheme && window.matchMedia('(prefers-color-scheme: dark)').matches)
  ) {
    isDark.value = true
    document.documentElement.classList.add('dark')
  }
}

onMounted(() => {
  initTheme()
  authStore.checkAuth()
  if (!appStore.publicSettingsLoaded) {
    appStore.fetchPublicSettings()
  }
})
</script>
