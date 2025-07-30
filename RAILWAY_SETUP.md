# 🚀 Railway Deployment Setup

## ✅ Required Environment Variables

In your Railway dashboard, go to **Variables** and set these:

### 🔑 Required Variables:
```bash
OPENAI_API_KEY=sk-...your-openai-api-key...
SECRET_KEY=your-secret-key-for-flask-sessions
```

### 🐘 Database (Automatic)
Railway PostgreSQL plugin automatically provides:
- `DATABASE_URL` - PostgreSQL connection string
- All PostgreSQL credentials

## 🔧 Railway Project Setup

1. **Create new Railway project**
2. **Add PostgreSQL plugin** (Database → PostgreSQL)
3. **Connect GitHub repository**: `https://github.com/kikompakt/kiki`
4. **Set environment variables** (see above)
5. **Deploy automatically triggers**

## 📝 Expected Deployment Flow

```bash
✅ PostgreSQL service starts
✅ App container builds from GitHub
✅ Gunicorn starts Flask app
✅ init_database() runs automatically:
   - Waits for DB connection (max 20 seconds)
   - Creates all tables (users, chat_session, chat_message, course, etc.)
   - Creates default users (admin/admin123, demo/demo123)
✅ App ready at Railway URL
```

## 🎯 Features Available After Deployment

- **Chat Interface**: Main app URL
- **Course Creation**: AI-powered course generation
- **Course Management**: `/courses` - View all courses
- **Course Download**: Text file download
- **Admin Panel**: Login with admin/admin123

## 🔍 Troubleshooting

### Database Issues:
- Check PostgreSQL plugin is added and running
- Verify `DATABASE_URL` environment variable exists

### OpenAI Issues:
- Verify `OPENAI_API_KEY` is set correctly
- Check OpenAI account has credits/access

### App Crashes:
- Check Railway logs for specific errors
- Verify all environment variables are set

## 📞 Support

If deployment fails:
1. Check Railway service logs
2. Verify environment variables
3. Ensure PostgreSQL plugin is active
4. Check GitHub repository access