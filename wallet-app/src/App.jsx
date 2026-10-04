import { useCallback, useEffect, useState } from 'react'
import { api, setToken, setUnauthorizedHandler } from './api.js'
import { makeT } from './i18n.js'
import Login from './screens/Login.jsx'
import Home from './screens/Home.jsx'
import SendFlow from './screens/SendFlow.jsx'
import HoldScreen from './screens/HoldScreen.jsx'
import Inbox from './screens/Inbox.jsx'
import History from './screens/History.jsx'
import Console from './screens/Console.jsx'
import AgentHome from './screens/AgentHome.jsx'

const TOKEN_KEY = 'upay_token'
const LANG_KEY = 'upay_lang'

export default function App() {
  const [lang, setLang] = useState(() => localStorage.getItem(LANG_KEY) || 'en')
  const [user, setUser] = useState(null)
  const [booting, setBooting] = useState(() => Boolean(localStorage.getItem(TOKEN_KEY)))
  const [notice, setNotice] = useState('')
  const [route, setRoute] = useState({ name: 'home' })
  const t = makeT(lang)

  const endSession = useCallback((message = '') => {
    localStorage.removeItem(TOKEN_KEY)
    setToken(null)
    setUser(null)
    setRoute({ name: 'home' })
    setNotice(message)
  }, [])

  useEffect(() => {
    document.documentElement.lang = lang
    localStorage.setItem(LANG_KEY, lang)
  }, [lang])

  // a session that the server no longer accepts sends the customer back to the login screen
  useEffect(() => {
    setUnauthorizedHandler(() => endSession('errSession'))
  }, [endSession])

  // returning customer: use the saved login if the server still accepts it
  useEffect(() => {
    const saved = localStorage.getItem(TOKEN_KEY)
    if (!saved) return
    setToken(saved)
    api
      .me()
      .then((r) => setUser(r.user))
      .catch((error) => endSession(error.code === 'network' ? 'errNetwork' : ''))
      .finally(() => setBooting(false))
  }, [endSession])

  function handleLoggedIn(token, loggedInUser) {
    localStorage.setItem(TOKEN_KEY, token)
    setToken(token)
    setNotice('')
    setUser(loggedInUser)
  }

  async function handleLogout() {
    try {
      await api.logout()
    } catch {
      /* logging out locally is enough if the server cannot be reached */
    }
    endSession('')
  }

  const toggleLang = () => setLang((l) => (l === 'en' ? 'bn' : 'en'))
  const setBalance = (balance) => setUser((u) => ({ ...u, balance }))
  const goHome = () => {
    setRoute({ name: 'home' })
    api.me().then((r) => setUser(r.user)).catch(() => {})
  }

  // a plain function (not a component) so that screens keep their state when the app re-renders
  const signed = () => {
    if (user.role === 'analyst') return <Console user={user} onLogout={handleLogout} onDemoReset={() => endSession('demoResetDone')} />
    if (user.role === 'agent') return <AgentHome user={user} t={t} lang={lang} onToggleLang={toggleLang} onLogout={handleLogout} />
    if (route.name === 'send') {
      return (
        <SendFlow user={user} t={t} lang={lang} onClose={goHome} onSent={setBalance}
          onHeld={(txn, balance) => { setBalance(balance); setRoute({ name: 'hold', txn }) }} />
      )
    }
    if (route.name === 'hold') return <HoldScreen txn={route.txn} t={t} lang={lang} onBack={goHome} onBalance={setBalance} />
    if (route.name === 'inbox') return <Inbox t={t} lang={lang} onBack={goHome} />
    if (route.name === 'history') return <History t={t} lang={lang} onBack={goHome} onOpenHold={(txn) => setRoute({ name: 'hold', txn })} />
    return <Home user={user} setUser={setUser} t={t} lang={lang} onToggleLang={toggleLang} onLogout={handleLogout} go={setRoute} />
  }

  return (
    <div className={`stage ${user?.role === 'analyst' ? 'wide' : ''}`}>
      <div className="phone">
        {booting ? (
          <div className="center-note">{t('working')}</div>
        ) : user ? (
          signed()
        ) : (
          <Login t={t} lang={lang} onToggleLang={toggleLang} onLoggedIn={handleLoggedIn} notice={notice ? t(notice) : ''} />
        )}
      </div>
    </div>
  )
}
