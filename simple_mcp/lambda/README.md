aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin [508226150422.dkr.ecr.us-east-1.amazonaws.com](http://508226150422.dkr.ecr.us-east-1.amazonaws.com/)

```json
docker buildx build --platform linux/amd64 -t  oncall-lambda2 . --load
```

docker tag oncall-lambda2:latest [508226150422.dkr.ecr.us-east-1.amazonaws.com/oncall-lambda2:latest](http://508226150422.dkr.ecr.us-east-1.amazonaws.com/oncall-lambda2:latest)

docker push [508226150422.dkr.ecr.us-east-1.amazonaws.com/oncall-lambda2:latest](http://508226150422.dkr.ecr.us-east-1.amazonaws.com/oncall-lambda2:latest)