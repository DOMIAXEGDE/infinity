#include <stdio.h>
#define M 16
char a[]="012",b[M+1],f[256]="system_safe.txt";
int l=4;

int w(FILE*p,int d){
	if(d==l)
		return fprintf(p,"%s\n",b)>0;
	for(int i=0;i<3;i++){
		b[d]=a[i];
		if(!w(p,d+1))
			return 0;
	}
	return 1;
}

int main(void){
	for(int m;;){
		printf(
			"\n[012 generator]\n"
			"1 length (%d)\n"
			"2 file (%s)\n"
			"3 generate\n0 exit\n> ",
			l,f
		);
		if(scanf("%d",&m)!=1)
			return 1;
		if(!m)
			break;
		if(m==1){
			printf("length 1-%d: ",M);
			if(scanf("%d",&l)!=1||l<1||l>M)
				return puts("invalid"),1;
			b[l]=0;
		}else if(m==2){
			printf("file: ");
			if(scanf("%255s",f)!=1)
				return 1;
		}else if(m==3){
			FILE*p=fopen(f,"w");
			if(!p)
				return perror("open"),1;
			b[l]=0;
			if(!w(p,0))
				return fclose(p),puts("gen failed"),1;
			fclose(p);
			puts("done");
		}else
			puts("invalid menu");
	}
	return 0;
}